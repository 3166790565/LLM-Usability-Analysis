from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# --- Provider Schemas ---
class ApiKey(BaseModel):
    id: str
    key: str
    remark: str = ""


class ModelConfig(BaseModel):
    id: str
    enabled: bool = True


class ProviderCreate(BaseModel):
    name: str
    url: str
    service_type: str = "openai"
    api_keys: List[ApiKey] = []
    models: List[ModelConfig] = []
    remark: str = ""


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    service_type: Optional[str] = None
    api_keys: Optional[List[ApiKey]] = None
    models: Optional[List[ModelConfig]] = None
    remark: Optional[str] = None


class Provider(ProviderCreate):
    id: str
    created_at: str
    updated_at: str


# --- Alias Schemas ---
class AliasCreate(BaseModel):
    alias: str
    real_model_id: str


# --- Settings Schemas ---
class SettingsUpdate(BaseModel):
    test_interval_seconds: Optional[int] = None
    request_timeout_seconds: Optional[int] = None
    max_workers: Optional[int] = None


# --- Test Result Schemas ---
class TestResult(BaseModel):
    model_config = {'protected_namespaces': ()}
    id: int
    provider_id: str
    provider_name: Optional[str] = None
    model_id: str
    alias_name: Optional[str] = None
    key_id: Optional[str] = None
    latency_ms: Optional[float] = None
    success: bool
    error_message: Optional[str] = None
    tested_at: str


# --- OpenAI API Schemas ---
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[List[str]] = None
    extra_body: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class ModelInfo(BaseModel):
    model_config = {'protected_namespaces': ()}
    id: str
    object: str = "model"
    created: int
    owned_by: str = "system"


class ModelList(BaseModel):
    model_config = {'protected_namespaces': ()}
    object: str = "list"
    data: List[ModelInfo]


# --- OpenAI Responses API Schema ---
class ResponsesRequest(BaseModel):
    model: str
    input: Any = ""
    max_output_tokens: Optional[int] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    extra_body: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


# --- Anthropic Messages API Schema ---
class AnthropicMessage(BaseModel):
    role: str
    content: str


class AnthropicRequest(BaseModel):
    model: str
    messages: List[AnthropicMessage]
    max_tokens: Optional[int] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    extra_body: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


# --- Gemini API Schema ---
class GeminiPart(BaseModel):
    text: str


class GeminiContent(BaseModel):
    parts: List[GeminiPart]
    role: Optional[str] = None


class GeminiRequest(BaseModel):
    contents: List[GeminiContent]
    generationConfig: Optional[Dict[str, Any]] = None
    safetySettings: Optional[List[Dict[str, Any]]] = None
