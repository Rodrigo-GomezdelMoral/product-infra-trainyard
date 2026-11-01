import { roles } from 'roles.bicep'

param location string
param tags object
param short string
param maxReplicas int
param logAnalyticsId string
param image string
param registryServer string
@description('Client id of the app registration Easy Auth signs users in with.')
param authClientId string
@description('Resource id and principal id of id-trainyard-app-<env>.')
param identity { id: string, principalId: string }
@description('Environment variables of the container.')
param settings object

var issuer = '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
var containers = {
  checkpoints: { key: '/workflow_name', paths: ['/workflow_name/?', '/checkpoint_id/?', '/timestamp/?'] }
  conversations: { key: '/owner', paths: ['/_ts/?'], ttl: 2592000 }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: 'cosmos-trainyard-${short}-swc'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard', capabilities: [{ name: 'EnableServerless' }], consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    backupPolicy: { type: 'Continuous', continuousModeProperties: { tier: 'Continuous7Days' } }
    disableLocalAuth: true, disableKeyBasedMetadataWriteAccess: true, minimalTlsVersion: 'Tls12', publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2026-03-15' = {
  parent: cosmos
  name: 'trainyard'
  properties: { resource: { id: 'trainyard' } }
}

resource collections 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2026-03-15' = [
  for item in items(containers): {
    parent: database
    name: item.key
    properties: {
      resource: {
        id: item.key, partitionKey: { paths: [item.value.key], kind: 'Hash' }, defaultTtl: item.value.?ttl
        indexingPolicy: { indexingMode: 'consistent', includedPaths: map(item.value.paths, path => { path: path }), excludedPaths: [{ path: '/*' }] }
      }
    }
  }
]

resource cosmosAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2026-03-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, roles.cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${roles.cosmosDataContributor}', principalId: identity.principalId
    scope: '${cosmos.id}/dbs/${database.name}'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: 'cae-trainyard-${short}-swc'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }, workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }], zoneRedundant: false
  }
}

#disable-next-line use-recent-api-versions
resource environmentLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: environment
  properties: { workspaceId: logAnalyticsId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}

resource app 'Microsoft.App/containerApps@2026-07-01' = {
  name: 'ca-trainyard-${short}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: environment.id, workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [{ server: registryServer, identity: identity.id }]
    }
    template: {
      containers: [
        {
          name: 'trainyard'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: map(items(union(settings, { COSMOS_ENDPOINT: cosmos.properties.documentEndpoint })), item => { name: item.key, value: item.value })
          probes: [
            for kind in ['Startup', 'Liveness', 'Readiness']: {
              type: kind, httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: kind == 'Startup' ? 12 : 3
            }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: maxReplicas, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }] }
    }
  }
  dependsOn: [cosmosAccess]
}

resource auth 'Microsoft.App/containerApps/authConfigs@2026-07-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'RedirectToLoginPage', redirectToProvider: 'azureactivedirectory', excludedPaths: ['/healthz'] }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true, registration: { clientId: authClientId, openIdIssuer: issuer }, validation: { allowedAudiences: ['api://${authClientId}'] }
      }
    }
    login: { tokenStore: { enabled: false } }
    httpSettings: { requireHttps: true }
  }
}

output id string = app.id
output name string = app.name
