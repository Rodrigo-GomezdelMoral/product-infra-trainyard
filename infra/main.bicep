targetScope = 'resourceGroup'

import { roles, roleId } from 'modules/roles.bicep'

@allowed(['staging', 'production'])
param env string
@description('Digest (sha256:...) of the image in the shared registry: built once per merge, promoted by digest, never rebuilt.')
param digest string
@description('Version the ML components are registered with: the image tag in staging, the release tag in production.')
param version string
@minLength(1)
@description('Client id of the app registration that Easy Auth signs users in with.')
param authClientId string
@secure()
@description('Address that receives the budget alerts.')
param alertEmail string
@description('Live traffic of the endpoint, read just before the deployment so that a redeploy never moves it.')
param traffic object = {}
@description('Mirrored traffic of the endpoint, read the same way.')
param mirrorTraffic object = {}
param sharedResourceGroup string
param registryName string
param logAnalyticsName string
param actionGroupName string
param foundryName string
param projectName string
param chatModel string
param location string = resourceGroup().location
param budgetStartDate string = utcNow('yyyy-MM-01')

var production = env == 'production'
var short = production ? 'prod' : 'stg'
var tags = { project: 'product-infra-trainyard', environment: env, owner: 'Rodrigo-GomezdelMoral' }
var shared = resourceGroup(sharedResourceGroup)
var logAnalyticsId = resourceId(sharedResourceGroup, 'Microsoft.OperationalInsights/workspaces', logAnalyticsName)

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName, scope: shared }
resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = { name: foundryName, scope: shared }
resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' existing = { parent: foundry, name: projectName }
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = { name: 'id-trainyard-app-${short}', location: location, tags: tags }
resource amlIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = { name: 'id-trainyard-aml-${short}', location: location, tags: tags }
resource epIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = { name: 'id-trainyard-ep-${short}', location: location, tags: tags }

var appRef = { id: appIdentity.id, principalId: appIdentity.properties.principalId }
var amlRef = { id: amlIdentity.id, principalId: amlIdentity.properties.principalId }
var epRef = { id: epIdentity.id, principalId: epIdentity.properties.principalId }

resource submitAsAml 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(amlIdentity.id, appIdentity.id, roles.identityOperator)
  scope: amlIdentity
  properties: { roleDefinitionId: roleId(roles.identityOperator), principalId: appIdentity.properties.principalId, principalType: 'ServicePrincipal' }
}

resource routeAsEp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(epIdentity.id, appIdentity.id, roles.identityOperator)
  scope: epIdentity
  properties: { roleDefinitionId: roleId(roles.identityOperator), principalId: appIdentity.properties.principalId, principalType: 'ServicePrincipal' }
}

module sharedAccess 'modules/shared.bicep' = {
  scope: shared
  params: {
    app: appRef, pulls: [appRef, amlRef, epRef], registryName: registryName, foundryName: foundryName, projectName: projectName
  }
}

module ml 'modules/ml.bicep' = {
  dependsOn: [sharedAccess]
  params: {
    location: location, tags: tags, short: short, production: production, logAnalyticsId: logAnalyticsId, registryId: registry.id
    aml: amlRef, ep: epRef, app: appRef, traffic: traffic, mirrorTraffic: mirrorTraffic
  }
}

module app 'modules/app.bicep' = {
  dependsOn: [sharedAccess, submitAsAml, routeAsEp]
  params: {
    location: location, tags: tags, short: short, maxReplicas: production ? 3 : 2, logAnalyticsId: logAnalyticsId, authClientId: authClientId
    image: '${registry.properties.loginServer}/product-infra-trainyard@${digest}', registryServer: registry.properties.loginServer
    identity: appRef
    settings: {
      ENVIRONMENT: env
      AZURE_CLIENT_ID: appIdentity.properties.clientId
      AZURE_SUBSCRIPTION_ID: subscription().subscriptionId
      AZURE_RESOURCE_GROUP: resourceGroup().name
      AML_WORKSPACE: ml.outputs.workspaceName
      AML_ENDPOINT: ml.outputs.endpointName
      AML_IDENTITY_CLIENT_ID: amlIdentity.properties.clientId
      ML_COMPONENT_VERSION: version
      FOUNDRY_PROJECT_ENDPOINT: project.properties.endpoints['AI Foundry API']
      FOUNDRY_MODEL: chatModel
      APPLICATIONINSIGHTS_CONNECTION_STRING: ml.outputs.connectionString
    }
  }
}

module monitor 'modules/monitor.bicep' = {
  params: {
    location: location, tags: tags, short: short, amount: production ? 80 : 60, budgetStartDate: budgetStartDate, alertEmail: alertEmail
    actionGroupId: resourceId(sharedResourceGroup, 'Microsoft.Insights/actionGroups', actionGroupName), insightsId: ml.outputs.insightsId
    workspaceId: ml.outputs.workspaceId, endpointId: ml.outputs.endpointId, appId: app.outputs.id
  }
}

output app string = app.outputs.name
output workspace string = ml.outputs.workspaceName
output endpoint string = ml.outputs.endpointName
output amlIdentityClientId string = amlIdentity.properties.clientId
