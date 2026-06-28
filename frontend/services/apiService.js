angular.module('supplyForgeApp')
    .factory('apiService', ['$http', function ($http) {
        var API_URL = 'http://localhost:8080';
        return {
            setApiUrl: function (url) {
                if (url) {
                    API_URL = url;
                }
            },
            getApiUrl: function () {
                return API_URL;
            },
            ping: function () {
                return $http.get(API_URL + '/api/v1/ping');
            },
            checkData: function () {
                return $http.get(API_URL + '/api/v1/products/check-data');
            },
            syncProducts: function (file, userId) {
                var fd = new FormData();
                fd.append('file', file);
                fd.append('userId', userId || 'user_default_001');
                return $http.post(API_URL + '/api/v1/products/sync', fd, {
                    transformRequest: angular.identity,
                    headers: { 'Content-Type': undefined }
                });
            },
            syncOrders: function (file, userId) {
                var fd = new FormData();
                fd.append('file', file);
                fd.append('userId', userId || 'user_default_001');
                return $http.post(API_URL + '/api/v1/orders/sync', fd, {
                    transformRequest: angular.identity,
                    headers: { 'Content-Type': undefined }
                });
            },
            analyzeFile: function (file) {
                var fd = new FormData();
                fd.append('file', file);
                return $http.post(API_URL + '/api/v1/import/analyze', fd, {
                    transformRequest: angular.identity,
                    headers: { 'Content-Type': undefined }
                });
            },
            processFile: function (file, mappingRule, userId) {
                var fd = new FormData();
                fd.append('file', file);
                fd.append('mappingRule', JSON.stringify(mappingRule));
                fd.append('userId', userId || 'user_default_001');
                return $http.post(API_URL + '/api/v1/import/process', fd, {
                    transformRequest: angular.identity,
                    headers: { 'Content-Type': undefined }
                });
            },
            clearData: function (userId) {
                return $http.delete(API_URL + '/api/v1/import/clear?userId=' + (userId || 'user_default_001'));
            },
            refreshDashboard: function (workspaceId, userId) {
                return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/dead-stock/refresh?userId=' + (userId || 'user_default_001'));
            },
            getDashboard: function (workspaceId, userId) {
                return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/dead-stock?userId=' + (userId || 'user_default_001'));
            },
            getAging: function (workspaceId, userId) {
                return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/aging?userId=' + (userId || 'user_default_001'));
            },
            getPortfolioCommand: function (workspaceId, userId) {
                return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/portfolio-command?userId=' + (userId || 'user_default_001'));
            },
            getFinancialAnalysis: function (workspaceId, userId, discount, accounting, skuId, skuName) {
                var url = API_URL + '/api/v1/workspaces/' + workspaceId + '/dashboard/financial-analysis?userId=' + (userId || 'user_default_001') + '&discount=' + (discount !== undefined ? discount : '0.35') + '&accounting=' + (accounting || 'FIFO');
                if (skuId)
                    url += '&skuId=' + encodeURIComponent(skuId);
                if (skuName)
                    url += '&skuName=' + encodeURIComponent(skuName);
                return $http.get(url);
            },
            getCandidates: function (workspaceId, userId) {
                return $http.get(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/candidates?userId=' + (userId || 'user_default_001'));
            },
            mergeProducts: function (workspaceId, parentId, childId) {
                return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/merge', {
                    parentSkuId: parentId,
                    childSkuId: childId
                });
            },
            undoMerge: function (workspaceId, parentId, childId) {
                return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/undo', {
                    parentSkuId: parentId,
                    childSkuId: childId
                });
            },
            ignorePair: function (workspaceId, skuAId, skuBId, userId) {
                return $http.post(API_URL + '/api/v1/workspaces/' + workspaceId + '/sku-merge/ignore', {
                    skuAId: skuAId,
                    skuBId: skuBId,
                    userId: userId || 'user_default_001'
                });
            }
        };
    }]);
//# sourceMappingURL=apiService.js.map