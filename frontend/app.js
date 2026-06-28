var app = angular.module('supplyForgeApp', []);
// File upload support directive
app.directive('fileModel', ['$parse', function ($parse) {
        return {
            restrict: 'A',
            link: function (scope, element, attrs) {
                var model = $parse(attrs.fileModel);
                var modelSetter = model.assign;
                element.bind('change', function () {
                    scope.$apply(function () {
                        modelSetter(scope, element[0].files[0]);
                    });
                });
            }
        };
    }]);
// ─── Main Controller ───
app.controller('MainController', ['$scope', '$window', '$timeout', 'apiService', function ($scope, $window, $timeout, apiService) {
        var self = this;
        // Core states
        self.stage = 'hero'; // hero | processing | mapping | dashboard | aging | recovery-copilot | dedup | command-center
        self.uploadFile = null;
        self.mappingData = null;
        self.dashboardData = null;
        self.agingData = null;
        self.portfolioData = null;
        self.portfolioLoading = false;
        self.dedupProposals = [];
        self.isProcessingBatch = false;
        self.activeCluster = null;
        // Mapping UI fields (used directly in index.html instead of component)
        self.mappingFields = [
            { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc nhãn hiệu của SKU' },
            { key: 'itemSku', label: 'Mã SKU', desc: 'Mã vạch hoặc mã ký tự SKU định danh' },
            { key: 'price', label: 'Giá bán', desc: 'Giá niêm yết bán lẻ cho người tiêu dùng' },
            { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng' },
            { key: 'stock', label: 'Tồn kho', desc: 'Số lượng đơn vị còn tồn kho' },
            { key: 'orderDate', label: 'Ngày ghi nhận', desc: 'Ngày nhập kho hoặc ngày giao dịch gần nhất' }
        ];
        self.finalMapping = {};
        // Workspace ID configuration
        self.workspaceId = 1;
        self.userId = 'user_default_001';
        // Scroll helper
        self.scrollToTop = function () {
            $window.scrollTo({ top: 0, behavior: 'smooth' });
        };
        // ─── Lifecycle ───
        // Check existing data on load
        apiService.checkData().then(function (res) {
            if (res.data && res.data.hasData) {
                console.log("Existing data found. Loading dashboard...");
                apiService.refreshDashboard(self.workspaceId, self.userId).then(function (dashboardRes) {
                    self.dashboardData = dashboardRes.data;
                    apiService.getAging(self.workspaceId, self.userId).then(function (agingRes) {
                        self.agingData = agingRes.data;
                        self.stage = 'dashboard';
                    });
                });
            }
        }).catch(function (err) {
            console.log("Failed to check existing data:", err);
        });
        self.startProcessing = function (file) {
            console.log("startProcessing called with file:", file);
            if (file) {
                self.uploadFile = file;
                self.stage = 'processing';
                console.log("Stage set to processing");
            }
        };
        self.handleMappingReady = function (data) {
            console.log("handleMappingReady called with data:", data);
            self.mappingData = data;
            // Auto-map columns from AI suggestions using column index
            self.finalMapping = {};
            if (data && data.aiSuggestions && data.headers) {
                var suggestions = data.aiSuggestions;
                var headers = data.headers;
                // Map AI suggestion indexes to our field keys
                var indexMap = {
                    'productName': null, // No direct suggestion, use fallback
                    'itemSku': suggestions.sku_column_index,
                    'price': suggestions.selling_price_column_index,
                    'cost': suggestions.cost_price_column_index,
                    'stock': suggestions.quantity_column_index,
                    'orderDate': suggestions.record_date_column_index
                };
                for (var key in indexMap) {
                    var idx = indexMap[key];
                    if (idx !== null && idx !== undefined && idx < headers.length) {
                        self.finalMapping[key] = headers[idx];
                    }
                }
                // Fallback: if no productName mapped, try to find 'Name' header or use first header
                if (!self.finalMapping['productName']) {
                    for (var i = 0; i < headers.length; i++) {
                        var h = headers[i].toLowerCase();
                        if (h.indexOf('name') !== -1 || h.indexOf('tên') !== -1 || h.indexOf('ten') !== -1) {
                            self.finalMapping['productName'] = headers[i];
                            break;
                        }
                    }
                }
                if (!self.finalMapping['itemSku'] && headers.length > 0) {
                    self.finalMapping['itemSku'] = headers[0];
                }
                console.log("Auto-mapped finalMapping:", self.finalMapping);
            }
            self.stage = 'mapping';
            console.log("Stage set to mapping");
        };
        self.handleConfirmMapping = function (finalMapping) {
            console.log("handleConfirmMapping called with finalMapping:", finalMapping);
            self.isProcessingBatch = true;
            apiService.processFile(self.uploadFile, finalMapping, self.userId).then(function () {
                console.log("processFile API success. Refreshing dashboard...");
                // After successfully import, reload dashboard & aging
                return apiService.refreshDashboard(self.workspaceId, self.userId);
            }).then(function (dashboardRes) {
                self.dashboardData = dashboardRes.data;
                return apiService.getAging(self.workspaceId, self.userId);
            }).then(function (agingRes) {
                self.agingData = agingRes.data;
                self.stage = 'dashboard';
            }).catch(function (err) {
                alert("Lỗi import dữ liệu: " + (err.data && err.data.error ? err.data.error : err.statusText));
            }).finally(function () {
                self.isProcessingBatch = false;
            });
        };
        self.handleOpenRecovery = function () {
            if (!self.agingData) {
                apiService.getAging(self.workspaceId, self.userId).then(function (res) {
                    self.agingData = res.data;
                    self.stage = 'aging';
                    self.scrollToTop();
                });
            }
            else {
                self.stage = 'aging';
                self.scrollToTop();
            }
        };
        self.handleOpenCommandCenter = function () {
            self.stage = 'command-center';
            self.portfolioLoading = true;
            self.scrollToTop();
            apiService.getPortfolioCommand(self.workspaceId, self.userId).then(function (res) {
                self.portfolioData = res.data;
                // Build active cluster mock from priority clusters
                if (self.portfolioData && self.portfolioData.priorityClusters && self.portfolioData.priorityClusters.length > 0) {
                    var pCluster = self.portfolioData.priorityClusters[0];
                    self.handleSelectCluster(pCluster);
                    // Reset stage to command-center since handleSelectCluster sets it to recovery-copilot
                    self.stage = 'command-center';
                }
            }).catch(function (err) {
                console.error("Failed to load portfolio command data:", err);
            }).finally(function () {
                self.portfolioLoading = false;
            });
        };
        self.handleSelectCluster = function (cluster) {
            if (!cluster)
                return;
            self.activeCluster = {
                clusterName: cluster.clusterName,
                industryCode: cluster.industryCode,
                recommendedBatchAction: cluster.recommendedBatchAction,
                estimatedClearDays: cluster.estimatedClearDays,
                totalFrozenValue: cluster.totalFrozenValue,
                totalPotentialRecovery: cluster.totalPotentialRecovery,
                items: (cluster.topSkuSamples || []).map(function (s) {
                    return {
                        skuName: s.name,
                        agingDays: s.daysInInventory,
                        stock: 100 // Mock stock for UI
                    };
                }),
                bundleAvailable: self.agingData && self.agingData.healthySkus && self.agingData.healthySkus.length > 0 ? {
                    hotItemName: self.agingData.healthySkus[0].name,
                    hotItemPrice: self.agingData.healthySkus[0].sellingPrice,
                    hotItemCost: self.agingData.healthySkus[0].costPrice,
                    bundleDiscountPct: 15
                } : undefined
            };
            self.stage = 'recovery-copilot';
            self.scrollToTop();
        };
        self.handleTriggerCopilot = function (item) {
            if (!item)
                return;
            var itemName = item.name || item.skuName || 'Sản phẩm chọn lọc';
            self.activeCluster = {
                targetSkuId: item.id || item.sku,
                targetSkuName: item.name || item.skuName,
                clusterName: 'Chiến dịch Khẩn cấp: ' + itemName,
                industryCode: item.industryContext ? item.industryContext.industryCode : 'GENERAL',
                recommendedBatchAction: 'Thanh lý khẩn cấp -70% kích cầu dòng tiền',
                recommendedDiscountPct: 70,
                estimatedClearDays: 7,
                totalFrozenValue: item.totalValue || 0,
                totalInitialCost: item.totalValue || 0,
                accumulatedStorageFee: item.accumulatedSunkCost || 0,
                totalSunkCost: (item.totalValue || 0) + (item.accumulatedSunkCost || 0),
                totalPotentialRecovery: (item.totalValue || 0) * 0.3,
                items: [{
                        skuName: itemName,
                        agingDays: item.daysInInventory || 90,
                        stock: item.quantity || 1
                    }],
                bundleAvailable: self.agingData && self.agingData.healthySkus && self.agingData.healthySkus.length > 0 ? {
                    hotItemName: self.agingData.healthySkus[0].name,
                    hotItemPrice: self.agingData.healthySkus[0].sellingPrice,
                    hotItemCost: self.agingData.healthySkus[0].costPrice,
                    logic: "Cùng phân khúc giá và tỷ lệ tiêu thụ cao"
                } : undefined
            };
            self.stage = 'recovery-copilot';
            self.scrollToTop();
        };
        self.handleFetchAndOpenTinder = function () {
            apiService.getCandidates(self.workspaceId, self.userId).then(function (res) {
                var data = res.data;
                if (!data || data.length === 0) {
                    alert("Tuyệt vời! Không còn SKU nào bị nghi trùng lặp.");
                    return;
                }
                // Map SkuPairDTO to MatchProposal format
                self.dedupProposals = data.map(function (p) {
                    return {
                        confidenceScore: 0.85,
                        skuA: {
                            id: p.skuAId,
                            skuCode: p.skuACode || p.skuAId,
                            name: p.skuAName,
                            price: p.skuAPrice,
                            stock: p.skuAStock,
                            source: p.skuASource
                        },
                        skuB: {
                            id: p.skuBId,
                            skuCode: p.skuBCode || p.skuBId,
                            name: p.skuBName,
                            price: p.skuBPrice,
                            stock: p.skuBStock,
                            source: p.skuBSource
                        }
                    };
                });
                self.stage = 'dedup';
                self.scrollToTop();
            }).catch(function () {
                alert("Lỗi tải danh sách SKU trùng.");
            });
        };
        self.handlePerformMerge = function (a, b) {
            apiService.mergeProducts(self.workspaceId, a.id, b.id).then(function () {
                console.log("Successfully merged:", a.name, "<-", b.name);
            }).catch(function (err) {
                console.error("Merge failed:", err);
            });
        };
        self.handleTinderComplete = function (mergedCount, ignoredCount) {
            // Refresh dashboard & aging stats, return to dashboard
            apiService.refreshDashboard(self.workspaceId, self.userId).then(function (dashboardRes) {
                self.dashboardData = dashboardRes.data;
                return apiService.getAging(self.workspaceId, self.userId);
            }).then(function (agingRes) {
                self.agingData = agingRes.data;
                self.stage = 'dashboard';
            }).catch(function (err) {
                console.error("Failed to refresh statistics:", err);
                self.stage = 'dashboard';
            });
        };
        self.clearAllDataAndRestart = function () {
            if (confirm('Bạn có chắc muốn xóa toàn bộ dữ liệu hiện tại để import file mới?')) {
                apiService.clearData(self.userId).then(function () {
                    self.uploadFile = null;
                    self.mappingData = null;
                    self.dashboardData = null;
                    self.agingData = null;
                    self.stage = 'hero';
                }).catch(function () {
                    alert('Lỗi xóa dữ liệu');
                });
            }
        };
        // Startup checks run inline above (no longer in self.init)
    }]);
//# sourceMappingURL=app.js.map