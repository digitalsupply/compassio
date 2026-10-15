PRESETS = {
    "opencode-go": {
        "base_url": "https://opencode.ai/inference/go/v1",
        "model": "deepseek-v4.1-flash",
        "extra_headers": {"x-opencode-session": "{{uuid}}"},
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "extra_headers": {},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "extra_headers": {},
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "extra_headers": {},
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
        "extra_headers": {},
    },
    "volcano": {
        "base_url": "https://ark.cn-volces.com/api/v3",
        "model": "",
        "extra_headers": {},
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "extra_headers": {},
    },
    "ollama": {
        "base_url": "http://host:11434/v1",
        "model": "",
        "extra_headers": {},
    },
    "custom": {
        "base_url": "",
        "model": "",
        "extra_headers": {},
    },
}


def get_preset(key: str) -> dict:
    return PRESETS.get(key, PRESETS["custom"].copy())
