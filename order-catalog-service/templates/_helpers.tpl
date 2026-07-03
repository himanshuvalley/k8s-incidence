{{- define "order-catalog-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "order-catalog-service.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "order-catalog-service.name" . -}}
{{- end -}}
{{- end }}

{{- define "order-catalog-service.labels" -}}
app.kubernetes.io/name: {{ include "order-catalog-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "order-catalog-service.imagePullSecrets" -}}
{{- if .Values.imageCredentials.enabled }}
imagePullSecrets:
  - name: {{ .Values.imageCredentials.secretName }}
{{- end }}
{{- end }}

{{- define "order-catalog-service.mongoUri" -}}
mongodb://{{ include "order-catalog-service.fullname" . }}-mongodb:{{ .Values.mongodb.port }}/{{ .Values.mongodb.database }}
{{- end }}
