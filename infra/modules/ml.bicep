import { roles, roleId } from 'roles.bicep'

param location string
param tags object
param short string
param production bool
param logAnalyticsId string
param registryId string
@description('Resource id and principal id of id-trainyard-aml-<env>: the workspace identity and every job node (ADR-006).')
param aml { id: string, principalId: string }
@description('Resource id and principal id of id-trainyard-ep-<env>, the endpoint identity.')
param ep { id: string, principalId: string }
param app { id: string, principalId: string }
@description('Live and mirrored traffic of the endpoint, passed back unchanged: deployments are the model lifecycle, not the Bicep.')
param traffic object
param mirrorTraffic object

var allLogs = { workspaceId: logAnalyticsId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
var storageGrants = [
  { identity: app, role: roles.blobReader }, { identity: ep, role: roles.blobContributor }
  { identity: aml, role: roles.blobContributor }, { identity: aml, role: roles.aiAdministrator }
]

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: 'sttrainyard${short}swc'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false, allowBlobPublicAccess: false, defaultToOAuthAuthentication: true, minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true, publicNetworkAccess: 'Enabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2026-06-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 7 }, containerDeleteRetentionPolicy: { enabled: true, days: 7 } }
}

resource vault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: 'kv-trainyard-${short}-swc'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId, sku: { family: 'A', name: 'standard' }, enableRbacAuthorization: true, enableSoftDelete: true
    softDeleteRetentionInDays: 7, enablePurgeProtection: production ? true : null, publicNetworkAccess: 'Enabled'
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-trainyard-${short}-swc'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logAnalyticsId, IngestionMode: 'LogAnalytics', DisableLocalAuth: true }
}

resource vaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in [roles.aiAdministrator, roles.vaultAdministrator]: {
    name: guid(vault.id, aml.id, role)
    scope: vault
    properties: { roleDefinitionId: roleId(role), principalId: aml.principalId, principalType: 'ServicePrincipal' }
  }
]

resource insightsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for grant in [{ identity: app, role: roles.metricsPublisher }, { identity: aml, role: roles.aiAdministrator }]: {
    name: guid(insights.id, grant.identity.id, grant.role)
    scope: insights
    properties: { roleDefinitionId: roleId(grant.role), principalId: grant.identity.principalId, principalType: 'ServicePrincipal' }
  }
]

#disable-next-line BCP081
resource workspace 'Microsoft.MachineLearningServices/workspaces@2026-09-01' = {
  name: 'mlw-trainyard-${short}-swc'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned,UserAssigned', userAssignedIdentities: { '${aml.id}': {} } }
  properties: {
    friendlyName: 'Trainyard (${short})', storageAccount: storage.id, keyVault: vault.id, applicationInsights: insights.id
    containerRegistry: registryId, primaryUserAssignedIdentity: aml.id, systemDatastoresAuthMode: 'identity', enableDataIsolation: true
    publicNetworkAccess: 'Enabled', hbiWorkspace: false, v1LegacyMode: false
  }
  dependsOn: [storageAccess, vaultAccess, insightsAccess]
}

resource workspaceAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for grant in [{ identity: app, role: roles.dataScientist }, { identity: aml, role: roles.aiAdministrator }]: {
    name: guid(workspace.id, grant.identity.id, grant.role)
    scope: workspace
    properties: { roleDefinitionId: roleId(grant.role), principalId: grant.identity.principalId, principalType: 'ServicePrincipal' }
  }
]

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for grant in storageGrants: {
    name: guid(storage.id, grant.identity.id, grant.role)
    scope: storage
    properties: { roleDefinitionId: roleId(grant.role), principalId: grant.identity.principalId, principalType: 'ServicePrincipal' }
  }
]

resource deployerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, deployer().objectId, roles.blobContributor)
  scope: storage
  properties: { roleDefinitionId: roleId(roles.blobContributor), principalId: deployer().objectId }
}

#disable-next-line BCP081
resource endpoint 'Microsoft.MachineLearningServices/workspaces/onlineEndpoints@2026-09-01' = {
  parent: workspace
  name: 'ep-trainyard-${short}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${ep.id}': {} } }
  properties: { authMode: 'AADToken', publicNetworkAccess: 'Enabled', traffic: traffic, mirrorTraffic: mirrorTraffic }
  dependsOn: [storageAccess]
}

resource trafficReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(endpoint.id, app.id, roles.monitoringReader)
  scope: endpoint
  properties: { roleDefinitionId: roleId(roles.monitoringReader), principalId: app.principalId, principalType: 'ServicePrincipal' }
}

#disable-next-line use-recent-api-versions
resource workspaceLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = { name: 'to-shared-workspace', scope: workspace, properties: allLogs }
#disable-next-line use-recent-api-versions
resource endpointLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = { name: 'to-shared-workspace', scope: endpoint, properties: allLogs }

output workspaceId string = workspace.id
output workspaceName string = workspace.name
output endpointId string = endpoint.id
output endpointName string = endpoint.name
output insightsId string = insights.id
output connectionString string = insights.properties.ConnectionString
