import { roles, roleId } from 'roles.bicep'

@description('id-trainyard-app-<env>, which calls gpt-5-mini. Assignment names use resource ids, which what-if can evaluate.')
param app { id: string, principalId: string }
@description('The identities that pull images from the shared registry: the app, the jobs and the endpoint.')
param pulls { id: string, principalId: string }[]
param registryName string
param foundryName string
param projectName string

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }
resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = { name: foundryName }
resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' existing = { parent: foundry, name: projectName }

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for pull in pulls: {
    name: guid(registry.id, pull.id, roles.acrPull)
    scope: registry
    properties: { roleDefinitionId: roleId(roles.acrPull), principalId: pull.principalId, principalType: 'ServicePrincipal' }
  }
]

resource model 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, roles.openAiUser)
  scope: foundry
  properties: { roleDefinitionId: roleId(roles.openAiUser), principalId: app.principalId, principalType: 'ServicePrincipal' }
}

resource agent 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, app.id, roles.foundryUser)
  scope: project
  properties: { roleDefinitionId: roleId(roles.foundryUser), principalId: app.principalId, principalType: 'ServicePrincipal' }
}
