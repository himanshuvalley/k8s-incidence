{{- define "alertmend-portal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "alertmend-portal.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "alertmend-portal.name" . -}}
{{- end -}}
{{- end }}

{{- define "alertmend-portal.web.fullname" -}}
{{- printf "%s-web" (include "alertmend-portal.fullname" .) -}}
{{- end }}

{{- define "alertmend-portal.api.fullname" -}}
{{- printf "%s-api" (include "alertmend-portal.fullname" .) -}}
{{- end }}

{{- define "alertmend-portal.db.fullname" -}}
{{- printf "%s-db" (include "alertmend-portal.fullname" .) -}}
{{- end }}

{{- define "alertmend-portal.labels" -}}
app.kubernetes.io/name: {{ include "alertmend-portal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
