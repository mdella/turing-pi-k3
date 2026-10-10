# Coder template "claude-workspace": one pod + one persistent home per user workspace, with Claude Code, git, glab, gpg.
# Push:  coder templates push claude-workspace -d coder/templates/claude-workspace --yes
# Central policy: ConfigMap claude-managed-settings (../../managed-settings.yaml) is mounted read-only at /etc/claude-code.
terraform {
  required_providers {
    coder      = { source = "coder/coder", version = "~> 2.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
  }
}

provider "coder" {}
provider "kubernetes" {} # in-cluster: Coder's service account (chart workspacePerms) in namespace coder

variable "namespace" {
  type    = string
  default = "coder"
}
variable "image" {
  type    = string
  default = "coder-workspace:20261010.2" # imported into node3's containerd (no registry yet)
}

data "coder_parameter" "cpu" {
  name         = "cpu"
  display_name = "CPU cores"
  type         = "number"
  default      = "2"
  mutable      = true
  option {
    name  = "1"
    value = "1"
  }
  option {
    name  = "2"
    value = "2"
  }
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory (GB)"
  type         = "number"
  default      = "4"
  mutable      = true
  option {
    name  = "2 GB"
    value = "2"
  }
  option {
    name  = "4 GB"
    value = "4"
  }
}

# "Connect GitLab": git (via Coder's GIT_ASKPASS) and glab (wrapper in the image) act as the user — no PAT to paste.
data "coder_external_auth" "gitlab" {
  id       = "gitlab"
  optional = true
}

data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

locals {
  name   = "coder-${lower(data.coder_workspace_owner.me.name)}-${lower(data.coder_workspace.me.name)}"
  labels = {
    "app.kubernetes.io/name"     = "coder-workspace"
    "app.kubernetes.io/instance" = local.name
    "com.coder.workspace.id"     = data.coder_workspace.me.id
    "com.coder.user.username"    = data.coder_workspace_owner.me.name
  }
  # The agent talks to coderd inside the cluster instead of hairpinning through Cloudflare.
  internal_url = "http://coder.${var.namespace}.svc.cluster.local"
}

resource "coder_agent" "main" {
  arch = "arm64"
  os   = "linux"
  dir  = "/home/coder"

  display_apps {
    web_terminal    = true
    ssh_helper      = true
    vscode          = false
    vscode_insiders = false
  }

  env = {
    GIT_AUTHOR_NAME     = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
    GIT_AUTHOR_EMAIL    = data.coder_workspace_owner.me.email
    GIT_COMMITTER_NAME  = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
    GIT_COMMITTER_EMAIL = data.coder_workspace_owner.me.email
    GITLAB_HOST         = "scm.geekstyle.net"
  }

  startup_script = <<-EOT
    set -e
    # First start on a fresh home volume: copy the skeleton dotfiles.
    [ -f ~/.bashrc ] || cp -rT /etc/skel ~
    mkdir -p ~/work
    git config --global init.defaultBranch main
  EOT

  metadata {
    display_name = "CPU"
    key          = "cpu"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }
  metadata {
    display_name = "Memory"
    key          = "mem"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }
  metadata {
    display_name = "Home disk"
    key          = "home"
    script       = "coder stat disk --path /home/coder"
    interval     = 60
    timeout      = 1
  }
}

resource "kubernetes_persistent_volume_claim_v1" "home" {
  metadata {
    name      = "${local.name}-home"
    namespace = var.namespace
    labels    = local.labels
  }
  wait_until_bound = false
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = "longhorn"
    resources {
      requests = { storage = "10Gi" }
    }
  }
  lifecycle {
    ignore_changes = all
  }
}

resource "kubernetes_deployment_v1" "main" {
  count            = data.coder_workspace.me.start_count
  wait_for_rollout = false
  metadata {
    name      = local.name
    namespace = var.namespace
    labels    = local.labels
  }
  spec {
    replicas = 1
    strategy { type = "Recreate" }
    selector { match_labels = { "com.coder.workspace.id" = data.coder_workspace.me.id } }
    template {
      metadata { labels = local.labels }
      spec {
        node_selector                    = { "kubernetes.io/hostname" = "k3-node3" } # where the image is imported
        automount_service_account_token  = false
        enable_service_links             = false
        termination_grace_period_seconds = 30
        security_context {
          run_as_user     = 1000
          run_as_group    = 1000
          fs_group        = 1000
          run_as_non_root = true
          seccomp_profile { type = "RuntimeDefault" }
        }
        container {
          name              = "dev"
          image             = var.image
          image_pull_policy = "Never"
          command           = ["sh", "-c", replace(coder_agent.main.init_script, data.coder_workspace.me.access_url, local.internal_url)]
          env {
            name  = "CODER_AGENT_TOKEN"
            value = coder_agent.main.token
          }
          env {
            name  = "CODER_AGENT_URL"
            value = local.internal_url
          }
          security_context {
            allow_privilege_escalation = false
            capabilities { drop = ["ALL"] }
          }
          resources {
            requests = { cpu = "250m", memory = "512Mi" }
            limits   = { cpu = data.coder_parameter.cpu.value, memory = "${data.coder_parameter.memory.value}Gi" }
          }
          volume_mount {
            name       = "home"
            mount_path = "/home/coder"
          }
          volume_mount {
            name       = "claude-policy"
            mount_path = "/etc/claude-code"
            read_only  = true
          }
        }
        volume {
          name = "home"
          persistent_volume_claim { claim_name = kubernetes_persistent_volume_claim_v1.home.metadata[0].name }
        }
        volume {
          name = "claude-policy"
          config_map { name = "claude-managed-settings" }
        }
      }
    }
  }
}
