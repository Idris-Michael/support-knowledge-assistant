output "api_url" {
  description = "Public URL of the API and the Support Desk console."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "key_vault_name" {
  description = "Set api-tokens and llm-proxy-token here after apply."
  value       = azurerm_key_vault.this.name
}

output "index_job" {
  description = "Run after each release: az containerapp job start -n <this> -g <resource group>."
  value       = azurerm_container_app_job.index.name
}
