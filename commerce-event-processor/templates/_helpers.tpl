{{- define "commerce-event-processor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "commerce-event-processor.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "commerce-event-processor.name" . -}}
{{- end -}}
{{- end }}

{{- define "commerce-event-processor.esHosts" -}}
{{- join "," .Values.elasticsearch.hosts -}}
{{- end }}
