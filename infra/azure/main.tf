# Azure Container Apps: the API (external ingress) and Ollama for embeddings (internal ingress only),
# plus a manual Container Apps Job that runs migrations and the indexer. Postgres Flexible Server with
# pgvector allow-listed, VNet-injected, no public endpoint. Secrets live in Key Vault and reach the
# containers through a user-assigned identity; API tokens and the model-gateway token are set out of
# band (az keyvault secret set), never in Terraform state. Deploy-ready, not deployed.

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${var.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name}-app"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

# --- Key Vault ---
resource "azurerm_key_vault" "this" {
  #checkov:skip=CKV2_AZURE_32:Apps reach the vault through a service endpoint on their subnet; a private endpoint is the production upgrade.
  #checkov:skip=CKV_AZURE_189:Default-deny ACL; open only to the apps subnet and the deployment pipeline's IP ranges.
  name                          = "kv-${var.name}-${substr(md5(azurerm_resource_group.this.id), 0, 6)}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 30
  public_network_access_enabled = true
  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    ip_rules                   = var.operator_ip_ranges
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
  tags = var.tags
}

resource "azurerm_role_assignment" "app_reads_secrets" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

locals {
  # Values are placeholders; real values are written with `az keyvault secret set` after apply.
  app_secrets = ["api-tokens", "llm-proxy-token"]
}

resource "azurerm_key_vault_secret" "app" { # nosemgrep: keyvault-ensure-secret-expires -- manual rotation; an expiry would break the app silently
  #checkov:skip=CKV_AZURE_41:Rotation is manual for the pilot; expiry would break the app silently.
  for_each     = toset(local.app_secrets)
  name         = each.value
  value        = "set-out-of-band"
  key_vault_id = azurerm_key_vault.this.id
  content_type = "text/plain"
  lifecycle {
    ignore_changes = [value]
  }
}

# --- Network: Container Apps and Postgres in one VNet; Postgres has no public endpoint ---
resource "azurerm_virtual_network" "this" {
  name                = "vnet-${var.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = ["10.40.0.0/16"]
  tags                = var.tags
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.40.0.0/23"]
  service_endpoints    = ["Microsoft.KeyVault"]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "db" {
  name                 = "snet-db"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.40.2.0/24"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_network_security_group" "apps" {
  name                = "nsg-${var.name}-apps"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
  # No custom rules: the apps call only Postgres, Key Vault, the internal Ollama app and the model
  # gateway. Restricting outbound traffic to those is the production step (Azure Firewall / UDR).
}

resource "azurerm_network_security_group" "db" {
  name                = "nsg-${var.name}-db"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags

  security_rule {
    name                       = "postgres-from-apps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.40.0.0/23"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "deny-other-vnet-inbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "apps" {
  subnet_id                 = azurerm_subnet.apps.id
  network_security_group_id = azurerm_network_security_group.apps.id
}

resource "azurerm_subnet_network_security_group_association" "db" {
  subnet_id                 = azurerm_subnet.db.id
  network_security_group_id = azurerm_network_security_group.db.id
}

resource "azurerm_private_dns_zone" "db" {
  name                = "${var.name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "db" {
  name                  = "link-${var.name}-db"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.db.name
  virtual_network_id    = azurerm_virtual_network.this.id
}

# --- Postgres ---
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  #checkov:skip=CKV_AZURE_136:Geo-redundant backup is a cost decision for production, not the pilot.
  #checkov:skip=CKV2_AZURE_57:VNet-injected into a delegated subnet with no public endpoint, so a private endpoint adds nothing.
  name                          = "psql-${var.name}-${substr(md5(azurerm_resource_group.this.id), 0, 6)}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  version                       = "17"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 14
  administrator_login           = "ska"
  administrator_password        = random_password.db.result
  public_network_access_enabled = false
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.db.id
  zone                          = "1"
  tags                          = var.tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.db]
}

# pgvector must be allow-listed before CREATE EXTENSION (the first migration) can run.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "VECTOR"
}

resource "azurerm_postgresql_flexible_server_database" "ska" {
  name      = "ska"
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_key_vault_secret" "database_url" { # nosemgrep: keyvault-ensure-secret-expires -- rotated with the DB password
  #checkov:skip=CKV_AZURE_41:Rotated with the database password, not on a fixed expiry.
  name         = "database-url"
  value        = "postgresql+psycopg://ska:${random_password.db.result}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/ska?sslmode=require"
  key_vault_id = azurerm_key_vault.this.id
  content_type = "text/plain"
}

# --- Container Apps ---
resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name}"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  tags                       = var.tags
}

locals {
  kv_secrets = merge(
    { for sname in local.app_secrets : sname => azurerm_key_vault_secret.app[sname].versionless_id },
    { "database-url" = azurerm_key_vault_secret.database_url.versionless_id },
  )
  secret_env = {
    API_TOKENS      = "api-tokens"      # checkov:skip=CKV_SECRET_6:the name of a Key Vault secret, not its value
    LLM_PROXY_TOKEN = "llm-proxy-token" # checkov:skip=CKV_SECRET_6:the name of a Key Vault secret, not its value
    DATABASE_URL    = "database-url"
  }
  plain_env = {
    RETRIEVER      = "pgvector"
    RETRIEVE_MODE  = "vector"
    EMBED_PROVIDER = "ollama"
    OLLAMA_URL     = "https://${azurerm_container_app.ollama.ingress[0].fqdn}"
    LLM_MODE       = "proxy"
    LLM_PROXY_URL  = var.model_gateway_url
  }
}

# Embeddings: nomic-embed-text on CPU. Internal ingress only; the model is pulled at start-up.
resource "azurerm_container_app" "ollama" {
  name                         = "ca-${var.name}-ollama"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = var.tags

  ingress {
    external_enabled = false
    target_port      = 11434
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2
    container {
      name    = "ollama"
      image   = var.ollama_image
      cpu     = 1
      memory  = "2Gi"
      command = ["/bin/sh", "-c", "ollama serve & sleep 5 && ollama pull nomic-embed-text && wait"]
      readiness_probe {
        transport = "HTTP"
        port      = 11434
        path      = "/api/tags"
      }
    }
  }
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name}-api"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "secret" {
    for_each = local.kv_secrets
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3
    container {
      name    = "api"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["ska-api"]
      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }
      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/readyz"
      }
    }
  }

  depends_on = [azurerm_role_assignment.app_reads_secrets]
}

# Migrations and indexing, run once per release (az containerapp job start).
resource "azurerm_container_app_job" "index" {
  name                         = "caj-${var.name}-index"
  location                     = azurerm_resource_group.this.location
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 1
  tags                         = var.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  template {
    container {
      name    = "index"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["/bin/sh", "-c", "alembic upgrade head && ska index --sections corpus/sections.jsonl"]
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name  = "OLLAMA_URL"
        value = local.plain_env.OLLAMA_URL
      }
    }
  }

  depends_on = [azurerm_role_assignment.app_reads_secrets, azurerm_postgresql_flexible_server_configuration.extensions]
}
