metadata description = 'cae-trainyard-env, the one Container Apps environment of Trainyard: production declares it, staging joins it (ADR-018).'
param name string
param location string
param tags object
param logAnalyticsId string

resource environment 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: name, location: location, tags: tags
  properties: { appLogsConfiguration: { destination: 'azure-monitor' }, workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }], zoneRedundant: false }
}

#disable-next-line use-recent-api-versions
resource logs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace', scope: environment, properties: { workspaceId: logAnalyticsId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}
