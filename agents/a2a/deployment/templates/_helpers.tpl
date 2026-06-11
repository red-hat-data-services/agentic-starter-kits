{{- define "a2a.partOfLabel" -}}
a2a-langgraph-crewai
{{- end }}

{{- define "a2a.chartLabel" -}}
{{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "a2a.labels" -}}
helm.sh/chart: {{ include "a2a.chartLabel" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ include "a2a.partOfLabel" . }}
{{- end }}

{{- define "a2a.secretName" -}}
{{- printf "%s-a2a-secrets" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
