{{/*
Expand the name of the chart.
*/}}
{{- define "loomai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "loomai.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "loomai.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "loomai.labels" -}}
helm.sh/chart: {{ include "loomai.chart" . }}
{{ include "loomai.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "loomai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "loomai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Hub fully qualified name
*/}}
{{- define "loomai.hub.fullname" -}}
{{- printf "%s-hub" (include "loomai.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Proxy fully qualified name
*/}}
{{- define "loomai.proxy.fullname" -}}
{{- printf "%s-proxy" (include "loomai.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Hub ServiceAccount name
*/}}
{{- define "loomai.hub.serviceAccountName" -}}
{{- include "loomai.hub.fullname" . }}
{{- end }}

{{/*
Derive the base URL. If hub.baseUrl is set, use it. Otherwise derive from ingress.
*/}}
{{- define "loomai.hub.baseUrl" -}}
{{- if .Values.hub.baseUrl }}
{{- .Values.hub.baseUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $firstHost := index .Values.ingress.hosts 0 }}
{{- if .Values.ingress.tls }}
{{- printf "https://%s" $firstHost.host }}
{{- else }}
{{- printf "http://%s" $firstHost.host }}
{{- end }}
{{- else }}
{{- printf "http://%s:8081" (include "loomai.hub.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Generate a random hex token if the provided value is empty.
Uses a lookup to check for an existing secret first so upgrades preserve the token.
*/}}
{{- define "loomai.proxyToken" -}}
{{- if .Values.proxy.secretToken }}
{{- .Values.proxy.secretToken }}
{{- else }}
{{- $existingSecret := lookup "v1" "Secret" .Release.Namespace (printf "%s-secret" (include "loomai.hub.fullname" .)) }}
{{- if and $existingSecret $existingSecret.data (index $existingSecret.data "PROXY_AUTH_TOKEN") }}
{{- index $existingSecret.data "PROXY_AUTH_TOKEN" | b64dec }}
{{- else }}
{{- randAlphaNum 64 | lower }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate a cookie secret if the provided value is empty.
*/}}
{{- define "loomai.cookieSecret" -}}
{{- if .Values.hub.cookie.secret }}
{{- .Values.hub.cookie.secret }}
{{- else }}
{{- $existingSecret := lookup "v1" "Secret" .Release.Namespace (printf "%s-secret" (include "loomai.hub.fullname" .)) }}
{{- if and $existingSecret $existingSecret.data (index $existingSecret.data "COOKIE_SECRET") }}
{{- index $existingSecret.data "COOKIE_SECRET" | b64dec }}
{{- else }}
{{- randAlphaNum 64 | lower }}
{{- end }}
{{- end }}
{{- end }}
