variable "aws_region" {
  description = "AWS region for all regional resources."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Lowercase name used in resource names."
  type        = string
  default     = "trading-data-lake"
}

variable "alert_email" {
  description = "Optional email endpoint. Subscription must be confirmed manually."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  type    = number
  default = 14
}
