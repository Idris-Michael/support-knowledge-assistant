output "api_dns_name" {
  description = "Point the API's DNS record at this load balancer."
  value       = aws_lb.api.dns_name
}

output "secret_names" {
  description = "Set these values after apply (aws secretsmanager put-secret-value)."
  value       = [for s in aws_secretsmanager_secret.app : s.name]
}

output "index_task" {
  description = "Run once per release: aws ecs run-task with this task definition and the command override shown."
  value = {
    task_definition = aws_ecs_task_definition.api.arn
    container       = "app"
    command         = ["/bin/sh", "-c", "alembic upgrade head && ska index --sections corpus/sections.jsonl"]
  }
}
