declare var angular: any;

angular.module('supplyForgeApp')
.factory('apiService', ['$http', function($http: any) {
    var API_URL = 'http://localhost:8080';

    return {
        setApiUrl: function(url: string) {
            if (url) {
                API_URL = url;
            }
        },
        getApiUrl: function() {
            return API_URL;
        },
        ping: function() {
            return $http.get(API_URL + '/api/v1/ping');
        },
        checkData: function() {
            return $http.get(API_URL + '/api/v1/products/check-data');
        },
        syncProducts: function(file: any, userId?: string) {
            var fd = new FormData();
            fd.append('file', file);
            fd.append('userId', userId || 'user_default_001');
            return $http.post(API_URL + '/api/v1/products/sync', fd, {
                transformRequest: angular.identity,
                headers: {'Content-Type': undefined}
            });
        },
        syncOrders: function(file: any, userId?: string) {
            var fd = new FormData();
            fd.append('file', file);
            fd.append('userId', userId || 'user_default_001');
            return $http.post(API_URL + '/api/v1/orders/sync', fd, {
                transformRequest: angular.identity,
                headers: {'Content-Type': undefined}
            });
        },
        analyzeFile: function(file: any) {
            var fd = new FormData();
            fd.append('file', file);
            return $http.post(API_URL + '/api/v1/import/analyze', fd, {
                transformRequest: angular.identity,
                headers: {'Content-Type': undefined}
            });
        },
        processFile: function(file: any, mappingRule: any, userId?: string) {
            var fd = new FormData();
            fd.append('file', file);
            fd.append('mappingRule', JSON.stringify(mappingRule));
            fd.append('userId', userId || 'user_default_001');
            return $http.post(API_URL + '/api/v1/import/process', fd, {
                transformRequest: angular.identity,
                headers: {'Content-Type': undefined}
            });
        },
        clearData: function(userId?: string) {
            return $http.delete(API_URL + '/api/v1/import/clear?userId=' + (userId || 'user_default_001'));
        },
        refreshDashboard: function(workspaceId: number, userId?: string) {
            return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/dead-stock/refresh?userId=' + (userId || 'user_default_001'));
        },
        getDashboard: function(workspaceId: number, userId?: string) {
            return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/dead-stock?userId=' + (userId || 'user_default_001'));
        },
        getAging: function(workspaceId: number, userId?: string) {
            return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/aging?userId=' + (userId || 'user_default_001'));
        },
        getPortfolioCommand: function(workspaceId: number, userId?: string) {
            return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/portfolio-command?userId=' + (userId || 'user_default_001'));
        },
        getFinancialAnalysis: function(workspaceId: number, userId?: string, discount?: number, accounting?: string, skuId?: string, skuName?: string) {
            var url = API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/financial-analysis?userId=' + (userId || 'user_default_001') + '&discount=' + (discount !== undefined ? discount : '0.35') + '&accounting=' + (accounting || 'FIFO');
            if (skuId) url += '&skuId=' + encodeURIComponent(skuId);
            if (skuName) url += '&skuName=' + encodeURIComponent(skuName);
            return $http.get(url);
        },
        getCandidates: function(workspaceId: number, userId?: string) {
            return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/candidates?userId=' + (userId || 'user_default_001'));
        },
        mergeProducts: function(workspaceId: number, parentId: number, childId: number) {
            return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/merge', {
                parentSkuId: parentId,
                childSkuId: childId
            });
        },
        undoMerge: function(workspaceId: number, parentId: number, childId: number) {
            return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/undo', {
                parentSkuId: parentId,
                childSkuId: childId
            });
        },
        ignorePair: function(workspaceId: number, skuAId: number, skuBId: number, userId?: string) {
            return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/ignore', {
                skuAId: skuAId,
                skuBId: skuBId,
                userId: userId || 'user_default_001'
            });
        }
    };
}]);
