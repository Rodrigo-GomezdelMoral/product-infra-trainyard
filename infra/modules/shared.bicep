import { roles, roleId } from 'roles.bicep'

@description('id-trainyard-app-<env>, which calls gpt-5-mini. Assignment names use resource ids, which what-if can evaluate.')
param app { id: string, principalId: string }
@description('AcrPull for the app, the jobs and the endpoint; Azure AI Administrator for the workspace identity, which Learn requires to hold Contributor on the linked registry (ADR-007).')
param grants { identity: { id: string, principalId: string }, role: string }[]
param registryName string
param foundryName string
param projectName string

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }
resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = { name: foundryName }
resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' existing = { parent: foundry, name: projectName }

resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for grant in grants: {
    name: guid(registry.id, grant.identity.id, grant.role)
    scope: registry
    properties: { roleDefinitionId: roleId(grant.role), principalId: grant.identity.principalId, principalType: 'ServicePrincipal' }
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
