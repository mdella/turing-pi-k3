# RK3588 NPU Setup — Node4 Prerequisite

RKLLaMA requires the `rknpu` kernel driver and associated device nodes to be present on k3-node4 before the pod can use the NPU. Without this, the RKLLM runtime silently falls back to CPU.

## Check current state

```bash
ssh ubuntu@192.168.4.104 'ls /dev/rknpu0 /dev/dma_heap /dev/rga /dev/dri/renderD129 2>&1'
```

If all four paths exist, skip to **Deploy RKLLaMA** below.

## Install the NPU kernel module (Ubuntu 24.04, kernel 6.1.0-rockchip)

The kernel 6.1.0-1025-rockchip (Joshua Riek Ubuntu image for Turing RK1) does not ship
the `rknpu` module as a loadable `.ko`. It must be built from Rockchip's source and
installed via DKMS.

```bash
ssh ubuntu@192.168.4.104

# Install build dependencies
sudo apt-get update
sudo apt-get install -y dkms git build-essential linux-headers-$(uname -r)

# Clone Rockchip's RKNN driver (matches kernel 6.1)
git clone https://github.com/airockchip/rknpu2.git --depth=1
cd rknpu2/rknpu-driver/

# Build and install via DKMS
sudo dkms add .
sudo dkms build rknpu/$(cat dkms.conf | grep PACKAGE_VERSION | cut -d= -f2 | tr -d '"')
sudo dkms install rknpu/$(cat dkms.conf | grep PACKAGE_VERSION | cut -d= -f2 | tr -d '"')

# Load the module
sudo modprobe rknpu

# Persist across reboots
echo 'rknpu' | sudo tee /etc/modules-load.d/rknpu.conf

# Verify
ls /dev/rknpu0 /dev/dma_heap
```

## Install the RKNN userspace runtime (on node4)

The RKLLaMA Docker image bundles `librknnrt.so` internally, so no host-side
userspace library is required for the container. However, the kernel driver must
expose the device node — the container's privileged flag gives it access.

## Verify NPU is functional

```bash
ssh ubuntu@192.168.4.104 'cat /sys/kernel/debug/rknpu/load 2>/dev/null || echo "load debug not available"'
```

## Deploy RKLLaMA

Once `/dev/rknpu0` exists on node4, apply in order:

```bash
# 1. Create the deployment and PVC
kubectl apply -f ai-services/rkllama.yaml

# 2. Download the pre-converted RKLLM model (~3 GB, one-time)
kubectl apply -f ai-services/rkllama-model-job.yaml
kubectl logs -n ai-services job/rkllama-pull-qwen-coder-3b -f

# 3. Verify the model name reported by RKLLaMA
kubectl exec -n ai-services deploy/rkllama -- curl -s localhost:8080/api/tags

# 4. Update the model name in ai-services/litellm.yaml if needed, then uncomment
#    the qwen2.5-coder:3b-npu block and apply:
kubectl apply -f ai-services/litellm.yaml
kubectl rollout restart deployment/litellm -n ai-services
```

## Expected performance after NPU enablement

| Model | CPU (Ollama) | NPU (RKLLaMA) | Gain |
|---|---|---|---|
| qwen2.5-coder:3b | 5.7 tok/s | ~7.7–8.5 tok/s | +35–50% |

See `ai-services/benchmark-results.md` for the CPU baseline methodology.
Re-run `ai-services/benchmark.yaml` (with the RKLLaMA model added to the
coding prompts section) to document NPU results once deployed.
