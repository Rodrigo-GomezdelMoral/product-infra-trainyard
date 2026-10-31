param location string
param tags object
param short string
param amount int
param budgetStartDate string
@secure()
@description('Address that receives the budget alerts.')
param alertEmail string
param actionGroupId string
param insightsId string
param workspaceId string
param endpointId string
param appId string

var tiles = loadJsonContent('../workbook.json')
var endpointMetrics = 'Microsoft.MachineLearningServices/workspaces/onlineEndpoints'
var fiveHundreds = [{ name: 'statusCodeClass', operator: 'Include', values: ['5xx'] }]
var metricAlerts = [
  { name: 'endpoint-5xx', text: 'Inference endpoint answered 5xx (REQ-07)', scope: endpointId, namespace: endpointMetrics, metric: 'RequestsPerMinute', aggregation: 'Average', threshold: 0, dimensions: fiveHundreds }
  { name: 'endpoint-p95', text: 'Inference p95 above the 400 ms SLO for 15 minutes (REQ-08)', scope: endpointId, namespace: endpointMetrics, metric: 'RequestLatency_P95', aggregation: 'Average', threshold: 400, dimensions: [] }
  {
    name: 'app-5xx', text: 'Chat app answered 5xx', scope: appId, namespace: 'Microsoft.App/containerApps', metric: 'Requests', aggregation: 'Total', threshold: 5
    dimensions: [{ name: 'statusCodeCategory', operator: 'Include', values: ['5xx'] }]
  }
]
var items = [
  for (tile, i) in tiles: {
    type: 3, name: 'tile-${i}'
    content: {
      version: 'KqlItem/1.0', title: tile.title, query: tile.query, size: 4, queryType: 0, resourceType: 'microsoft.resources/resourcegroups'
      crossComponentResources: [resourceGroup().id], timeContext: { durationMs: tile.days * 86400000 }
    }
  }
]

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'trainyard-workbook')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'Trainyard SLA, SLO, KPIs and health (${short})', category: 'workbook', sourceId: insightsId
    serializedData: string({ version: 'Notebook/1.0', items: items, fallbackResourceIds: [resourceGroup().id] })
  }
}

resource metricRules 'Microsoft.Insights/metricAlerts@2026-01-01' = [
  for alert in metricAlerts: {
    name: 'alert-trainyard-${short}-${alert.name}'
    location: 'global'
    tags: tags
    properties: {
      description: alert.text, severity: 2, enabled: true, scopes: [alert.scope], evaluationFrequency: 'PT5M', windowSize: 'PT15M', autoMitigate: true
      actions: [{ actionGroupId: actionGroupId }]
      criteria: {
        'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
        allOf: [
          {
            criterionType: 'StaticThresholdCriterion', name: alert.name, metricNamespace: alert.namespace, metricName: alert.metric, operator: 'GreaterThan'
            threshold: alert.threshold, timeAggregation: alert.aggregation, dimensions: alert.dimensions
          }
        ]
      }
    }
  }
]

resource runFailures 'Microsoft.Insights/scheduledQueryRules@2026-03-01' = {
  name: 'alert-trainyard-${short}-run-failed'
  location: location
  tags: tags
  properties: {
    description: 'A pipeline run failed, or a monitor run breached a threshold (REQ-04)', severity: 2, enabled: true, scopes: [workspaceId]
    evaluationFrequency: 'PT15M', windowSize: 'PT15M', actions: { actionGroups: [actionGroupId] }
    criteria: {
      allOf: [
        {
          query: 'AmlRunStatusChangedEvent | where Status == "Failed"', timeAggregation: 'Count', operator: 'GreaterThan', threshold: 0
          dimensions: [{ name: 'ExperimentName', operator: 'Include', values: ['*'] }], failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
  }
}

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: 'budget-trainyard-${short}'
  properties: {
    category: 'Cost', amount: amount, timeGrain: 'Monthly', timePeriod: { startDate: budgetStartDate }
    notifications: {
      'actual-80': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [alertEmail] }
      'forecast-100': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [alertEmail] }
    }
  }
}
