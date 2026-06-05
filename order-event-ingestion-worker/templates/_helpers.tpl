{{- define "order-event-ingestion-worker.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "order-event-ingestion-worker.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "order-event-ingestion-worker.name" . -}}
{{- end -}}
{{- end }}

{{- define "order-event-ingestion-worker.elasticsearch.fullname" -}}
{{- printf "%s-elasticsearch" (include "order-event-ingestion-worker.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "order-event-ingestion-worker.elasticsearch.host" -}}
{{- if .Values.elasticsearch.deployInCluster -}}
{{- include "order-event-ingestion-worker.elasticsearch.fullname" . -}}
{{- else -}}
{{- required "elasticsearch.host is required when elasticsearch.deployInCluster=false" .Values.elasticsearch.host -}}
{{- end -}}
{{- end }}
