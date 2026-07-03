{{- define "retail-hub.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "retail-hub.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "retail-hub.name" . -}}
{{- end -}}
{{- end }}

{{- define "retail-hub.labels" -}}
app.kubernetes.io/name: {{ include "retail-hub.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "retail-hub.component" -}}
{{- printf "%s-%s" (include "retail-hub.fullname" .) .component -}}
{{- end }}

{{- define "retail-hub.imagePullSecrets" -}}
{{- if .Values.imageCredentials.enabled }}
imagePullSecrets:
  - name: {{ .Values.imageCredentials.secretName }}
{{- end }}
{{- end }}

{{- define "retail-hub.mongoUri" -}}
mongodb://{{ .Values.mongodb.username }}:{{ .Values.mongodb.password }}@{{ include "retail-hub.fullname" . }}-mongodb:{{ .Values.mongodb.port }}/{{ .Values.mongodb.database }}?authSource=admin
{{- end }}

{{- define "retail-hub.redisUrl" -}}
redis://{{ include "retail-hub.fullname" . }}-redis:{{ .Values.redis.port }}
{{- end }}
