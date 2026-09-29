#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0"]
# ///
"""
FLUX.2 image-generation MCP server for Claude Code.

Talks to a ComfyUI server (default: the Mac Studio via k3-node1 at
http://192.168.4.101:8199) and exposes a `generate_image` tool that runs the
validated FLUX.2 [dev] Q8_0 GGUF + Turbo-LoRA text-to-image workflow.

Run (deps handled by uv):
    uv run --with mcp /path/to/flux2_mcp.py
Register with Claude Code:
    claude mcp add flux2 -- uv run --with mcp /ABS/PATH/flux2_mcp.py
Override the endpoint if needed:
    COMFYUI_URL=http://192.168.4.101:8199
"""
import base64, json, os, time, urllib.request, urllib.parse, random
from mcp.server.fastmcp import FastMCP, Image

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://192.168.4.101:8199").rstrip("/")
POLL_TIMEOUT = int(os.environ.get("FLUX2_TIMEOUT", "900"))  # seconds to wait for a render

mcp = FastMCP("flux2")


def _workflow(prompt, negative, seed, steps, guidance, width, height):
    # API-format FLUX.2 [dev] GGUF + Turbo-LoRA graph (validated on the Mac Studio).
    return {
        "1":  {"class_type": "UnetLoaderGGUF",        "inputs": {"unet_name": "flux2-dev-Q8_0.gguf"}},
        "2":  {"class_type": "LoraLoaderModelOnly",   "inputs": {"model": ["1", 0], "lora_name": "Flux2TurboComfyv2.safetensors", "strength_model": 1.0}},
        "3":  {"class_type": "CLIPLoader",            "inputs": {"clip_name": "mistral_3_small_flux2_fp8.safetensors", "type": "flux2", "device": "default"}},
        "4":  {"class_type": "CLIPTextEncode",        "inputs": {"clip": ["3", 0], "text": prompt}},
        "5":  {"class_type": "FluxGuidance",          "inputs": {"conditioning": ["4", 0], "guidance": guidance}},
        "6":  {"class_type": "BasicGuider",           "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}},
        "7":  {"class_type": "RandomNoise",           "inputs": {"noise_seed": seed}},
        "8":  {"class_type": "KSamplerSelect",        "inputs": {"sampler_name": "euler"}},
        "9":  {"class_type": "Flux2Scheduler",        "inputs": {"steps": steps, "width": width, "height": height}},
        "10": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["7", 0], "guider": ["6", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["10", 0]}},
        "12": {"class_type": "VAELoader",             "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "13": {"class_type": "VAEDecode",             "inputs": {"samples": ["11", 0], "vae": ["12", 0]}},
        "14": {"class_type": "SaveImage",             "inputs": {"images": ["13", 0], "filename_prefix": "flux2_mcp"}},
    }


def _post(path, obj):
    req = urllib.request.Request(COMFYUI_URL + path, data=json.dumps(obj).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _get(path):
    with urllib.request.urlopen(COMFYUI_URL + path, timeout=60) as r:
        return r.read()


@mcp.tool()
def generate_image(prompt: str, seed: int = 0, steps: int = 8,
                   guidance: float = 4.0, width: int = 1024, height: int = 1024) -> Image:
    """Generate an image from a text prompt with FLUX.2 [dev] on the Mac Studio.

    Args:
        prompt: What to draw. FLUX.2 renders in-image text well; put wanted text in quotes.
        seed: 0 = random each call; set a value for reproducible results.
        steps: Sampling steps (Turbo LoRA is tuned for ~8; 4 = faster/rougher).
        guidance: FLUX guidance scale (default 4.0).
        width: Image width in px (multiple of 16).
        height: Image height in px (multiple of 16).
    """
    if seed == 0:
        seed = random.randint(1, 2**63 - 1)
    wf = _workflow(prompt, "", seed, steps, guidance, width, height)
    pid = _post("/prompt", {"prompt": wf, "client_id": "flux2-mcp"})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < POLL_TIMEOUT:
        hist = json.loads(_get("/history/" + pid))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI render error: " + json.dumps(entry.get("status")))
            for node_out in entry.get("outputs", {}).values():
                for im in node_out.get("images", []):
                    q = urllib.parse.urlencode({"filename": im["filename"],
                                                "subfolder": im.get("subfolder", ""),
                                                "type": im.get("type", "output")})
                    return Image(data=_get("/view?" + q), format="png")
        time.sleep(3)
    raise TimeoutError("FLUX.2 render exceeded %ss" % POLL_TIMEOUT)


if __name__ == "__main__":
    mcp.run()
