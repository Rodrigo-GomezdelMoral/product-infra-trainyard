@export()
@description('Built-in role definition ids: public constants, allowlisted one by one in test_no_identifiers.')
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  dataScientist: 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  blobReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  metricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
  identityOperator: 'f1a07417-d97a-45cb-824c-7a7467783830'
  monitoringReader: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
  aiAdministrator: 'b78c5d69-af96-48a3-bf8d-a8b4d589de94'
  vaultAdministrator: '00482a5a-887f-4fb3-b363-3b7fe8e74483'
  cosmosDataContributor: '00000000-0000-0000-0000-000000000002'
}

@export()
func roleId(id string) string => subscriptionResourceId('Microsoft.Authorization/roleDefinitions', id)
