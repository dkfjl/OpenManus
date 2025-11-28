import json
import threading
import tomllib
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


class LLMSettings(BaseModel):
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key")
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )
    temperature: float = Field(1.0, description="Sampling temperature")
    api_type: str = Field(..., description="Azure, Openai, or Ollama")
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")


class ProxySettings(BaseModel):
    server: str = Field(None, description="Proxy server address")
    username: Optional[str] = Field(None, description="Proxy username")
    password: Optional[str] = Field(None, description="Proxy password")


class SearchSettings(BaseModel):
    engine: str = Field(default="Google", description="Search engine the llm to use")
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )


class RunflowSettings(BaseModel):
    use_data_analysis_agent: bool = Field(
        default=False, description="Enable data analysis agent in run flow"
    )


class DocumentSettings(BaseModel):
    default_language: str = Field(
        "zh", description="Default language for structured documents"
    )
    outline_sections: int = Field(
        6, description="Target number of sections when building outlines"
    )
    min_section_words: int = Field(
        400, description="Minimum word count per section when writing content"
    )
    table_of_contents_title: str = Field(
        "目录", description="Label to use for the table of contents heading"
    )


class EmbeddingSettings(BaseModel):
    profile_name: str = Field(
        "default",
        description="LLM profile used to source API credentials for embedding calls",
    )
    model: str = Field(
        "text-embedding-3-small", description="Embedding model or deployment name"
    )
    batch_size: int = Field(16, description="Maximum inputs per embedding request")
    request_timeout: int = Field(30, description="Embedding request timeout (seconds)")
    max_retries: int = Field(3, description="Retry attempts for transient failures")
    normalize: bool = Field(True, description="Whether to L2-normalize embeddings")


class KnowledgeBaseSettings(BaseModel):
    storage_dir: str = Field(
        "vector_store", description="Workspace-relative directory for FAISS data"
    )
    chunk_size: int = Field(800, description="Character length of each text chunk")
    chunk_overlap: int = Field(200, description="Overlap size between chunks")
    top_k: int = Field(5, description="Default number of retrieval hits")
    max_context_chars: int = Field(
        2000, description="Max chars when concatenating retrieved context"
    )
    embedding: EmbeddingSettings = Field(
        default_factory=EmbeddingSettings, description="Embedding configuration"
    )


class AIPPTSettings(BaseModel):
    """Configuration for AIPPT third-party API"""
    base_url: str = Field(
        "http://192.168.1.119:3001", description="AIPPT API base URL"
    )
    request_timeout: int = Field(
        300, description="Request timeout in seconds"
    )
    default_style: str = Field(
        "通用", description="Default PPT style (通用/学术风/职场风/教育风/营销风)"
    )
    default_model: str = Field(
        "gemini-3-pro-preview", description="Default AI model"
    )


class BrowserSettings(BaseModel):
    headless: bool = Field(False, description="Whether to run browser in headless mode")
    disable_security: bool = Field(
        True, description="Disable browser security features"
    )
    extra_chromium_args: List[str] = Field(
        default_factory=list, description="Extra arguments to pass to the browser"
    )
    chrome_instance_path: Optional[str] = Field(
        None, description="Path to a Chrome instance to use"
    )
    wss_url: Optional[str] = Field(
        None, description="Connect to a browser instance via WebSocket"
    )
    cdp_url: Optional[str] = Field(
        None, description="Connect to a browser instance via CDP"
    )
    proxy: Optional[ProxySettings] = Field(
        None, description="Proxy settings for the browser"
    )
    max_content_length: int = Field(
        2000, description="Maximum length for content retrieval operations"
    )


class SandboxSettings(BaseModel):
    """Configuration for the execution sandbox"""

    use_sandbox: bool = Field(False, description="Whether to use the sandbox")
    image: str = Field("python:3.12-slim", description="Base image")
    work_dir: str = Field("/workspace", description="Container working directory")
    memory_limit: str = Field("512m", description="Memory limit")
    cpu_limit: float = Field(1.0, description="CPU limit")
    timeout: int = Field(300, description="Default command timeout (seconds)")
    network_enabled: bool = Field(
        False, description="Whether network access is allowed"
    )


class DaytonaSettings(BaseModel):
    daytona_api_key: str = Field(
        "",
        description="Daytona API key used for sandbox automation (leave blank to disable)",
    )
    daytona_server_url: Optional[str] = Field(
        "https://app.daytona.io/api", description=""
    )
    daytona_target: Optional[str] = Field("us", description="enum ['eu', 'us']")
    sandbox_image_name: Optional[str] = Field("whitezxj/sandbox:0.1.0", description="")
    sandbox_entrypoint: Optional[str] = Field(
        "/usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf",
        description="",
    )
    # sandbox_id: Optional[str] = Field(
    #     None, description="ID of the daytona sandbox to use, if any"
    # )
    VNC_password: Optional[str] = Field(
        "123456", description="VNC password for the vnc service in sandbox"
    )


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""

    type: str = Field(..., description="Server connection type (sse or stdio)")
    url: Optional[str] = Field(None, description="Server URL for SSE connections")
    command: Optional[str] = Field(None, description="Command for stdio connections")
    args: List[str] = Field(
        default_factory=list, description="Arguments for stdio command"
    )


class MCPSettings(BaseModel):
    """Configuration for MCP (Model Context Protocol)"""

    server_reference: str = Field(
        "app.mcp.server", description="Module reference for the MCP server"
    )
    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict, description="MCP server configurations"
    )

    @classmethod
    def load_server_config(cls) -> Dict[str, MCPServerConfig]:
        """Load MCP server configuration from JSON file"""
        config_path = PROJECT_ROOT / "config" / "mcp.json"

        try:
            config_file = config_path if config_path.exists() else None
            if not config_file:
                return {}

            with config_file.open() as f:
                data = json.load(f)
                servers = {}

                for server_id, server_config in data.get("mcpServers", {}).items():
                    servers[server_id] = MCPServerConfig(
                        type=server_config["type"],
                        url=server_config.get("url"),
                        command=server_config.get("command"),
                        args=server_config.get("args", []),
                    )
                return servers
        except Exception as e:
            raise ValueError(f"Failed to load MCP server config: {e}")


class AppConfig(BaseModel):
    llm: Dict[str, LLMSettings]
    sandbox: Optional[SandboxSettings] = Field(
        None, description="Sandbox configuration"
    )
    browser_config: Optional[BrowserSettings] = Field(
        None, description="Browser configuration"
    )
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )
    mcp_config: Optional[MCPSettings] = Field(None, description="MCP configuration")
    run_flow_config: Optional[RunflowSettings] = Field(
        None, description="Run flow configuration"
    )
    daytona_config: Optional[DaytonaSettings] = Field(
        None, description="Daytona configuration"
    )
    aippt_config: AIPPTSettings = Field(
        default_factory=AIPPTSettings, description="AIPPT API configuration"
    )
    document_config: DocumentSettings = Field(
        default_factory=DocumentSettings, description="Document generation settings"
    )
    knowledge_base_config: KnowledgeBaseSettings = Field(
        default_factory=KnowledgeBaseSettings,
        description="Vector knowledge base configuration",
    )

    class Config:
        arbitrary_types_allowed = True


class Config:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        cls = self.__class__
        if not cls._initialized:
            with cls._lock:
                if not cls._initialized:
                    self._config = None
                    self._load_initial_config()
                    cls._initialized = True

    @staticmethod
    def _get_config_path() -> Path:
        root = PROJECT_ROOT
        config_path = root / "config" / "config.toml"
        if config_path.exists():
            return config_path
        example_path = root / "config" / "config.example.toml"
        if example_path.exists():
            return example_path
        raise FileNotFoundError("No configuration file found in config directory")

    def _load_config(self) -> dict:
        config_path = self._get_config_path()
        with config_path.open("rb") as f:
            return tomllib.load(f)

    def _load_initial_config(self):
        raw_config = self._load_config()
        base_llm = raw_config.get("llm", {})
        llm_overrides = {
            k: v for k, v in raw_config.get("llm", {}).items() if isinstance(v, dict)
        }

        default_settings = {
            "model": base_llm.get("model"),
            "base_url": base_llm.get("base_url"),
            "api_key": base_llm.get("api_key"),
            "max_tokens": base_llm.get("max_tokens", 4096),
            "max_input_tokens": base_llm.get("max_input_tokens"),
            "temperature": base_llm.get("temperature", 1.0),
            "api_type": base_llm.get("api_type", ""),
            "api_version": base_llm.get("api_version", ""),
        }

        # handle browser config.
        browser_config = raw_config.get("browser", {})
        browser_settings = None

        if browser_config:
            # handle proxy settings.
            proxy_config = browser_config.get("proxy", {})
            proxy_settings = None

            if proxy_config and proxy_config.get("server"):
                proxy_settings = ProxySettings(
                    **{
                        k: v
                        for k, v in proxy_config.items()
                        if k in ["server", "username", "password"] and v
                    }
                )

            # filter valid browser config parameters.
            valid_browser_params = {
                k: v
                for k, v in browser_config.items()
                if k in BrowserSettings.__annotations__ and v is not None
            }

            # if there is proxy settings, add it to the parameters.
            if proxy_settings:
                valid_browser_params["proxy"] = proxy_settings

            # only create BrowserSettings when there are valid parameters.
            if valid_browser_params:
                browser_settings = BrowserSettings(**valid_browser_params)

        search_config = raw_config.get("search", {})
        search_settings = None
        if search_config:
            search_settings = SearchSettings(**search_config)
        sandbox_config = raw_config.get("sandbox", {})
        if sandbox_config:
            sandbox_settings = SandboxSettings(**sandbox_config)
        else:
            sandbox_settings = SandboxSettings()
        daytona_config = raw_config.get("daytona")
        if daytona_config is None:
            daytona_settings = DaytonaSettings()
        else:
            daytona_settings = DaytonaSettings(**daytona_config)

        mcp_config = raw_config.get("mcp", {})
        mcp_settings = None
        if mcp_config:
            # Load server configurations from JSON
            mcp_config["servers"] = MCPSettings.load_server_config()
            mcp_settings = MCPSettings(**mcp_config)
        else:
            mcp_settings = MCPSettings(servers=MCPSettings.load_server_config())

        run_flow_config = raw_config.get("runflow")
        if run_flow_config:
            run_flow_settings = RunflowSettings(**run_flow_config)
        else:
            run_flow_settings = RunflowSettings()
        document_config = raw_config.get("document")
        if document_config:
            document_settings = DocumentSettings(**document_config)
        else:
            document_settings = DocumentSettings()
        knowledge_base_config = raw_config.get("knowledge_base")
        if knowledge_base_config:
            knowledge_base_settings = KnowledgeBaseSettings(**knowledge_base_config)
        else:
            knowledge_base_settings = KnowledgeBaseSettings()
        aippt_config = raw_config.get("aippt")
        if aippt_config:
            aippt_settings = AIPPTSettings(**aippt_config)
        else:
            aippt_settings = AIPPTSettings()
        config_dict = {
            "llm": {
                "default": default_settings,
                **{
                    name: {**default_settings, **override_config}
                    for name, override_config in llm_overrides.items()
                },
            },
            "sandbox": sandbox_settings,
            "browser_config": browser_settings,
            "search_config": search_settings,
            "mcp_config": mcp_settings,
            "run_flow_config": run_flow_settings,
            "daytona_config": daytona_settings,
            "aippt_config": aippt_settings,
            "document_config": document_settings,
            "knowledge_base_config": knowledge_base_settings,
        }

        self._config = AppConfig(**config_dict)

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        return self._config.llm

    @property
    def sandbox(self) -> SandboxSettings:
        return self._config.sandbox

    @property
    def daytona(self) -> Optional[DaytonaSettings]:
        return self._config.daytona_config

    @property
    def browser_config(self) -> Optional[BrowserSettings]:
        return self._config.browser_config

    @property
    def search_config(self) -> Optional[SearchSettings]:
        return self._config.search_config

    @property
    def mcp_config(self) -> MCPSettings:
        """Get the MCP configuration"""
        return self._config.mcp_config

    @property
    def run_flow_config(self) -> RunflowSettings:
        """Get the Run Flow configuration"""
        return self._config.run_flow_config

    @property
    def document_config(self) -> DocumentSettings:
        """Get structured document configuration"""
        return self._config.document_config

    @property
    def knowledge_base_config(self) -> KnowledgeBaseSettings:
        """Get vector knowledge base configuration"""
        return self._config.knowledge_base_config

    @property
    def aippt_config(self) -> AIPPTSettings:
        """Get AIPPT API configuration"""
        return self._config.aippt_config

    @property
    def workspace_root(self) -> Path:
        """Get the workspace root directory"""
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """Get the root path of the application"""
        return PROJECT_ROOT


config = Config()
