from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.parse
from pathlib import Path
from typing import Any

from core.paths import ensure_under_root
from core.settings import settings
from integrations.apimart_client import APIMartClient, is_remote_url, public_project_url


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.provider = settings.gemini_provider
        self.apimart = APIMartClient(self.api_key)

    def build_segment_prompt(
        self,
        segment_index: int,
        total_segments: int,
        source_segment_path: str | Path,
        original_video_path: str | Path,
        product_image_path: str | Path,
        previous_tail_frame_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if self.provider == "mock":
            return self._mock_prompt(segment_index, total_segments)
        if self.provider != "apimart":
            raise ValueError("real Gemini calls currently require GEMINI_PROVIDER=apimart")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or APIMART_API_KEY is required when GEMINI_PROVIDER=apimart")
        if settings.gemini_request_format == "chat":
            return self._build_prompt_with_apimart_chat(
                segment_index,
                total_segments,
                source_segment_path,
                original_video_path,
                product_image_path,
                previous_tail_frame_path,
            )
        if settings.gemini_request_format != "native":
            raise ValueError("GEMINI_REQUEST_FORMAT must be native or chat")
        return self._build_prompt_with_apimart_native(
            segment_index,
            total_segments,
            source_segment_path,
            product_image_path,
            previous_tail_frame_path,
        )

    def _build_prompt_with_apimart_native(
        self,
        segment_index: int,
        total_segments: int,
        source_segment_path: str | Path,
        product_image_path: str | Path,
        previous_tail_frame_path: str | Path | None,
    ) -> dict[str, Any]:
        instruction = self._analysis_instruction(segment_index, total_segments, bool(previous_tail_frame_path))
        parts: list[dict[str, Any]] = [
            {
                "text": (
                    instruction
                    + "\n\n只分析当前上传的源视频片段，不要把完整原片作为参考视频。"
                    + "请输出能直接交给 Seedance 2.0 的复刻提示词。"
                )
            },
            {"text": "当前需要复刻的源视频片段："},
            self._media_part_for_native(source_segment_path, default_mime="video/mp4"),
            {"text": "用户上传的目标产品图："},
            self._media_part_for_native(product_image_path, default_mime="image/jpeg"),
        ]
        if previous_tail_frame_path:
            parts.extend(
                [
                    {"text": "上一段 Seedance 返回的尾帧图，将作为当前段首帧连续性参考："},
                    self._media_part_for_native(previous_tail_frame_path, default_mime="image/jpeg"),
                ]
            )
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "你是电商短视频复刻提示词分析器，只输出严格 JSON。"
                            "JSON 字段必须包含 prompt、shot_notes、warnings。"
                        )
                    }
                ]
            },
            "generationConfig": {
                "temperature": 0.35,
                "responseMimeType": "application/json",
            },
        }
        data = self.apimart.json_request(self._native_endpoint(), body)
        return self._parse_prompt_json(self._extract_gemini_text(data))

    def _build_prompt_with_apimart_chat(
        self,
        segment_index: int,
        total_segments: int,
        source_segment_path: str | Path,
        original_video_path: str | Path,
        product_image_path: str | Path,
        previous_tail_frame_path: str | Path | None,
    ) -> dict[str, Any]:
        source_segment_url = public_project_url(source_segment_path)
        original_video_url = public_project_url(original_video_path)
        product_image_url = self._image_url_for_chat(product_image_path)
        previous_tail_url = self._image_url_for_chat(previous_tail_frame_path) if previous_tail_frame_path else ""

        instruction = self._analysis_instruction(segment_index, total_segments, bool(previous_tail_url))
        materials = [
            f"Full original video URL: {original_video_url}",
            f"Current source segment URL: {source_segment_url}",
            f"Product image URL: {product_image_url}",
        ]
        if previous_tail_url:
            materials.append(f"Previous Seedance returned tail frame URL: {previous_tail_url}")

        content: list[dict[str, Any]] = [
            {"type": "text", "text": instruction + "\n\n" + "\n".join(materials)},
            {"type": "image_url", "image_url": {"url": product_image_url}},
        ]
        if previous_tail_url:
            content.append({"type": "image_url", "image_url": {"url": previous_tail_url}})

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是电商短视频复刻提示词分析器，只输出严格 JSON。"},
                {"role": "user", "content": content},
            ],
            "stream": False,
            "temperature": 0.35,
        }
        data = self.apimart.json_request(settings.apimart_chat_endpoint, body)
        return self._parse_prompt_json(self._extract_chat_text(data))

    def _native_endpoint(self) -> str:
        if settings.gemini_endpoint:
            return settings.gemini_endpoint
        encoded_model = urllib.parse.quote(self.model, safe="")
        return f"{settings.apimart_base_url}/v1beta/models/{encoded_model}:generateContent"

    def _media_part_for_native(self, path: str | Path, default_mime: str) -> dict[str, Any]:
        if is_remote_url(path):
            text = str(path)
            if text.startswith("data:"):
                header, _, payload = text.partition(",")
                mime = header[5:].split(";", 1)[0] or default_mime
                return {"inlineData": {"mimeType": mime, "data": payload}}
            return {"fileData": {"mimeType": self._mime_type(path, default_mime), "fileUri": text}}

        source = ensure_under_root(path)
        mime = self._mime_type(source, default_mime)
        if settings.public_base_url:
            return {"fileData": {"mimeType": mime, "fileUri": public_project_url(source)}}

        raw = source.read_bytes()
        if len(raw) > 20 * 1024 * 1024:
            raise RuntimeError(
                f"{source.name} is larger than 20MB. Configure PUBLIC_BASE_URL or upload a public file URL for Gemini video input."
            )
        return {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode("ascii")}}

    def _mime_type(self, path: str | Path, default_mime: str) -> str:
        name = urllib.parse.urlsplit(str(path)).path or str(path)
        return mimetypes.guess_type(name)[0] or default_mime

    def _image_url_for_chat(self, path: str | Path | None) -> str:
        if not path:
            return ""
        if is_remote_url(path):
            return str(path)
        source = ensure_under_root(path)
        if settings.public_base_url:
            return public_project_url(source)
        raw = source.read_bytes()
        if len(raw) > 20 * 1024 * 1024:
            raise RuntimeError("image is larger than 20MB and PUBLIC_BASE_URL is not configured")
        mime = mimetypes.guess_type(source.name)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    def _parse_prompt_json(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = {"prompt": cleaned, "shot_notes": [], "warnings": ["Gemini did not return strict JSON"]}
            else:
                parsed = {"prompt": cleaned, "shot_notes": [], "warnings": ["Gemini did not return strict JSON"]}
        parsed.setdefault("prompt", cleaned)
        parsed.setdefault("shot_notes", [])
        parsed.setdefault("warnings", [])
        return parsed

    def _mock_prompt(self, segment_index: int, total_segments: int) -> dict[str, Any]:
        if segment_index > 1:
            continuity = "以上一段 Seedance 返回的尾帧作为首帧，保持产品位置、手部动作和背景连续。"
        else:
            continuity = "以产品图为主体，复刻原视频第一段的构图和开场节奏。"
        prompt = (
            f"生成第 {segment_index}/{total_segments} 段 9:16 带货短视频，时长不超过 15 秒。"
            f"{continuity} 参考当前原视频片段的镜头语言、运镜、节奏、达人展示动作和卖点表达，"
            "将画面中的原商品替换为用户上传产品图中的商品。保持真实电商短视频风格，"
            "不要出现原品牌商标，不要生成夸大功效字幕，镜头稳定，产品清晰可见。"
        )
        return {
            "prompt": prompt,
            "shot_notes": [
                "识别原片段的景别、机位、动作顺序和转场点。",
                "产品外观以产品图为准，优先保持包装和颜色一致。",
                "15-30 秒总片长质量最好，超过 30 秒要降低镜头复杂度。",
            ],
            "warnings": ["未配置 APIMART_API_KEY/GEMINI_API_KEY，当前使用本地规则生成提示词。"],
        }

    def _analysis_instruction(self, segment_index: int, total_segments: int, has_tail: bool) -> str:
        if has_tail:
            tail_rule = "上一段 Seedance 返回尾帧会作为当前段首帧，请在提示词里强约束首帧连续性。"
        else:
            tail_rule = "这是第一段，不需要衔接上一段尾帧。"
        return (
            "请只基于当前上传的源视频片段分析节奏、动作和镜头，并结合产品图生成 Seedance 2.0 提示词。"
            f"现在要生成第 {segment_index}/{total_segments} 段，每段最长 15 秒。{tail_rule}"
            "只返回 JSON，字段必须是 prompt、shot_notes、warnings。"
            "prompt 要直接可用于 APIMart Seedance 2.0，重点写：镜头、动作、产品替换、构图、光线、节奏、首尾帧连续性。"
            "避免原品牌标识，避免夸大功效或医疗承诺，输出中文。"
        )

    def _extract_chat_text(self, data: dict[str, Any]) -> str:
        payload = data.get("data", data)
        choices = payload.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        return json.dumps(data, ensure_ascii=False)

    def _extract_gemini_text(self, data: dict[str, Any]) -> str:
        payload = data.get("data", data)
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict) and part.get("text")]
            if texts:
                return "\n".join(texts).strip()
        return self._extract_chat_text(data)
