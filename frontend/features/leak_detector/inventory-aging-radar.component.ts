declare var angular: any;

angular.module('supplyForgeApp')
    .component('inventoryAgingRadar', {
        bindings: {
            data: '<',
            onTriggerCopilot: '&'
        },
        template: `
<div class="space-y-12">
        
        <!-- F&B Expiration date Alerts -->
        <div ng-if="$ctrl.data.expiredDeactivatedCount > 0 || $ctrl.data.nearExpiryWarnings.length > 0" class="mb-12 space-y-4">
            <div ng-if="$ctrl.data.expiredDeactivatedCount > 0" 
                 class="border border-danger/30 bg-danger/5 rounded-2xl p-6 flex items-start gap-4 shadow-sm">
                <span class="text-2xl text-danger mt-1">⚠️</span>
                <div>
                    <h3 class="font-tight font-bold text-danger text-lg">Phát hiện Thực phẩm quá hạn sử dụng (F&B Auto-Deactivation)</h3>
                    <p class="text-secondary text-sm mt-1">
                        Hệ thống đã tự động vô hiệu hóa <strong class="text-danger font-mono font-bold">{{ $ctrl.data.expiredDeactivatedCount }}</strong> SKU có ngày hết hạn cũ hơn hôm nay nhằm bảo đảm tiêu chuẩn an toàn thực phẩm.
                    </p>
                </div>
            </div>

            <div ng-if="$ctrl.data.nearExpiryWarnings.length > 0" 
                 class="border border-warn/30 bg-warn/5 rounded-2xl p-6 flex flex-col gap-4 shadow-sm">
                <div class="flex items-start gap-4">
                    <span class="text-2xl text-warn mt-1">🕒</span>
                    <div>
                        <h3 class="font-tight font-bold text-warn text-lg">Cảnh báo Cận Hạn Sử Dụng (Dưới 15 ngày)</h3>
                        <p class="text-secondary text-sm mt-1">
                            Có <strong class="text-warn font-mono font-bold">{{ $ctrl.data.nearExpiryWarnings.length }}</strong> SKU thực phẩm sắp hết hạn. Vui lòng triển khai chiến dịch Markdown Dynamic hoặc Donation ngay lập tức để tận dụng chính sách Tax Shield.
                        </p>
                    </div>
                </div>

                <!-- Horizontal scrolling list of near-expiry SKUs -->
                <div class="overflow-x-auto pb-2 flex gap-4">
                    <div ng-repeat="warnSku in $ctrl.data.nearExpiryWarnings" 
                         class="bg-surface border border-warn/30 rounded-xl p-4 min-w-[240px] max-w-[280px] flex-shrink-0 shadow-sm">
                        <div class="text-xs font-mono text-warn uppercase tracking-wider mb-1 font-bold">Còn {{ warnSku.daysLeft }} ngày nữa hết hạn</div>
                        <div class="text-sm font-bold text-primary truncate" title="{{ warnSku.name }}">{{ warnSku.name }}</div>
                        <div class="text-xs text-secondary mt-0.5 font-mono">SKU: {{ warnSku.sku }}</div>
                        <div class="flex justify-between items-center mt-3 pt-2 border-t border-warn/10">
                            <span class="text-xs text-secondary">Tồn: <strong class="text-primary font-mono">{{ warnSku.stock }}</strong></span>
                            <span class="text-[10px] text-warn font-mono font-bold bg-warn/10 px-2 py-0.5 rounded">{{ warnSku.expirationDate }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Hero stats Header -->
        <div class="mb-16">
            <span class="text-xs font-mono text-accent tracking-widest uppercase font-bold">
                Inventory Aging Radar · Phân tích Chi phí Ẩn
            </span>
            <h2 class="font-tight font-black tracking-tightest text-primary text-4xl sm:text-5xl leading-tight mt-4 mb-4">
                Tồn kho của bạn đang <span class="text-danger">"đốt"</span> <span class="text-danger tabular-nums">{{ $ctrl.formatVND($ctrl.data.totalBleedingRateMonthly) }}</span> mỗi tháng.
            </h2>
            <p class="text-secondary text-sm max-w-2xl leading-relaxed">
                Chi phí này bao gồm phí lưu trữ thực tế, khấu hao giảm giá trị hàng lỗi thời và đặc biệt là chi phí cơ hội chôn vốn.
            </p>

            <!-- Holding Cost Breakdowns -->
            <div class="grid grid-cols-1 sm:grid-cols-4 gap-6 mt-8 bg-surface p-6 rounded-3xl border border-border-base shadow-material">
                <div>
                    <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-1 font-semibold">Chi phí chìm lũy kế</div>
                    <div class="font-tight font-black text-warn text-2xl tabular-nums">
                        {{ $ctrl.formatVND($ctrl.data.accumulatedSunkCost) }}
                    </div>
                    <div class="text-xs text-secondary mt-1 font-mono">25%/năm × tuổi tồn thực tế</div>
                </div>
                <div class="border-t sm:border-t-0 sm:border-l border-border-base pt-4 sm:pt-0 sm:pl-6">
                    <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-1 font-semibold">Khấu hao lỗi thời</div>
                    <div class="font-tight font-black text-danger text-2xl tabular-nums">
                        {{ $ctrl.formatVND($ctrl.data.depreciationCostMonthly) }}
                    </div>
                    <div class="text-xs text-secondary mt-1 font-mono">10%/năm × vốn kẹt</div>
                </div>
                <div class="border-t sm:border-t-0 sm:border-l border-border-base pt-4 sm:pt-0 sm:pl-6">
                    <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-1 font-semibold">Phí cơ hội (Chôn vốn)</div>
                    <div class="font-tight font-black text-warn text-2xl tabular-nums">
                        {{ $ctrl.formatVND($ctrl.data.opportunityCostMonthly) }}
                    </div>
                    <div class="text-xs text-secondary mt-1 font-mono">10%/năm × vốn kẹt</div>
                </div>
                <div class="border-t sm:border-t-0 sm:border-l border-border-base pt-4 sm:pt-0 sm:pl-6">
                    <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-1 font-semibold">Tổng vốn đóng băng</div>
                    <div class="font-tight font-black text-primary text-2xl tabular-nums">
                        {{ $ctrl.formatVND($ctrl.data.totalFrozenValue) }}
                    </div>
                    <div class="text-xs text-secondary mt-1 font-mono">Watchlist + Slow + Dead</div>
                </div>
            </div>
        </div>

        <!-- Lifecycle distribution bars -->
        <div class="mb-12">
            <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-3 font-semibold">
                Phân bổ vốn tồn kho theo vòng đời
            </div>
            <div class="flex h-3 rounded-full overflow-hidden gap-px bg-gray-200 shadow-inner">
                <div class="bg-blue-400 rounded-l-full" ng-style="{ width: $ctrl.getBarWidth($ctrl.data.totalHealthyValue) + '%' }" title="Healthy"></div>
                <div class="bg-warn" ng-style="{ width: $ctrl.getBarWidth($ctrl.data.totalWatchlistValue) + '%' }" title="Watchlist"></div>
                <div class="bg-orange-500" ng-style="{ width: $ctrl.getBarWidth($ctrl.data.totalSlowMovingValue) + '%' }" title="Slow Moving"></div>
                <div class="bg-danger rounded-r-full" ng-style="{ width: $ctrl.getBarWidth($ctrl.data.totalDeadStockValue) + '%' }" title="Dead Stock"></div>
            </div>
            <div class="flex justify-between text-xs font-mono text-secondary mt-2 font-semibold">
                <span>0 ngày (Khỏe mạnh)</span>
                <span>30 ngày</span>
                <span>60 ngày</span>
                <span>90 ngày</span>
                <span>91+ ngày (Chết)</span>
            </div>
        </div>

        <!-- 4 Bucket grids -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-16">
            <!-- Healthy block -->
            <div class="border border-border-base bg-surface rounded-2xl p-6 shadow-material hover:shadow-material-lg transition-all">
                <div class="flex justify-between mb-4">
                    <span class="text-xs font-mono text-secondary uppercase tracking-widest font-semibold">0-30 Ngày</span>
                    <span class="text-xs font-mono text-success font-bold bg-success/10 px-2 py-0.5 rounded">OK</span>
                </div>
                <div class="font-tight font-black text-2xl text-primary">Khỏe mạnh</div>
                <div class="text-secondary text-xs mt-1 font-mono mb-4">{{ $ctrl.data.healthySkus.length }} SKU</div>
                <div class="font-mono text-sm font-semibold tabular-nums text-primary">{{ $ctrl.formatVND($ctrl.data.totalHealthyValue) }}</div>
            </div>

            <!-- Watchlist block -->
            <div class="border border-warn/30 bg-warn/5 rounded-2xl p-6 shadow-material hover:shadow-material-lg transition-all">
                <div class="flex justify-between mb-4">
                    <span class="text-xs font-mono text-warn uppercase tracking-widest font-semibold">31-60 Ngày</span>
                    <span class="text-xs font-mono text-warn font-bold bg-warn/10 px-2 py-0.5 rounded">WARN</span>
                </div>
                <div class="font-tight font-black text-2xl text-warn">Cảnh báo</div>
                <div class="text-secondary text-xs mt-1 font-mono mb-4">{{ $ctrl.data.watchlistSkus.length }} SKU</div>
                <div class="font-mono text-sm font-semibold tabular-nums text-warn">{{ $ctrl.formatVND($ctrl.data.totalWatchlistValue) }}</div>
            </div>

            <!-- Slow moving block -->
            <div class="border border-orange-500/30 bg-orange-500/5 rounded-2xl p-6 shadow-material hover:shadow-material-lg transition-all">
                <div class="flex justify-between mb-4">
                    <span class="text-xs font-mono text-orange-600 uppercase tracking-widest font-semibold">61-90 Ngày</span>
                    <span class="text-xs font-mono text-orange-600 font-bold bg-orange-500/10 px-2 py-0.5 rounded">SLOW</span>
                </div>
                <div class="font-tight font-black text-2xl text-orange-600">Bán chậm</div>
                <div class="text-secondary text-xs mt-1 font-mono mb-4">{{ $ctrl.data.slowMovingSkus.length }} SKU</div>
                <div class="font-mono text-sm font-semibold tabular-nums text-orange-600">{{ $ctrl.formatVND($ctrl.data.totalSlowMovingValue) }}</div>
            </div>

            <!-- Dead Stock block -->
            <div class="border border-danger/30 bg-danger/5 rounded-2xl p-6 shadow-material hover:shadow-material-lg transition-all">
                <div class="flex justify-between mb-4">
                    <span class="text-xs font-mono text-danger uppercase tracking-widest font-semibold">91+ Ngày</span>
                    <span class="text-xs font-mono text-danger font-bold bg-danger/10 px-2 py-0.5 rounded">DEAD</span>
                </div>
                <div class="font-tight font-black text-2xl text-danger">Tồn kho chết</div>
                <div class="text-secondary text-xs mt-1 font-mono mb-4">{{ $ctrl.data.deadStockSkus.length }} SKU</div>
                <div class="font-mono text-sm font-semibold tabular-nums text-danger">{{ $ctrl.formatVND($ctrl.data.totalDeadStockValue) }}</div>
            </div>
        </div>

        <!-- Detailed Table with Unit Velocity Analyzer -->
        <div class="border border-border-base bg-surface rounded-3xl shadow-material overflow-hidden">
            <div class="px-6 py-5 border-b border-border-base flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-gray-50/50">
                <div>
                    <span class="text-xs font-mono text-primary uppercase tracking-widest font-bold">
                        Bảng phân tích tốc độ bán &amp; tuổi hàng tồn kho thực chiến
                    </span>
                    <p class="text-xs text-secondary mt-1 font-mono">So sánh chi phí chìm chôn vốn &amp; vận tốc bán điều chỉnh mùa vụ</p>
                </div>
                <!-- Filter category tabs -->
                <div class="flex items-center gap-2">
                    <button ng-click="$ctrl.setBucketFilter('all')" class="px-3 py-1.5 rounded-lg text-xs font-mono border transition-all shadow-sm" 
                            ng-class="{'bg-accent text-white border-accent font-bold': $ctrl.bucketFilter === 'all', 'bg-surface border-border-base text-secondary hover:bg-gray-100': $ctrl.bucketFilter !== 'all'}">
                        Tất cả ({{ $ctrl.getAllSkusCount() }})
                    </button>
                    <button ng-click="$ctrl.setBucketFilter('DEAD_STOCK')" class="px-3 py-1.5 rounded-lg text-xs font-mono border transition-all shadow-sm"
                            ng-class="{'bg-danger text-white border-danger font-bold': $ctrl.bucketFilter === 'DEAD_STOCK', 'bg-surface border-border-base text-secondary hover:bg-gray-100': $ctrl.bucketFilter !== 'DEAD_STOCK'}">
                        Chết ({{ $ctrl.data.deadStockSkus.length }})
                    </button>
                    <button ng-click="$ctrl.setBucketFilter('SLOW_MOVING')" class="px-3 py-1.5 rounded-lg text-xs font-mono border transition-all shadow-sm"
                            ng-class="{'bg-warn text-white border-warn font-bold': $ctrl.bucketFilter === 'SLOW_MOVING', 'bg-surface border-border-base text-secondary hover:bg-gray-100': $ctrl.bucketFilter !== 'SLOW_MOVING'}">
                        Chậm ({{ $ctrl.data.slowMovingSkus.length }})
                    </button>
                </div>
            </div>

            <!-- List table with Sticky Header & Compact Density -->
            <div class="overflow-x-auto max-h-[600px]">
                <table class="w-full text-left border-collapse">
                    <thead class="sticky top-0 z-10 bg-gray-100/95 backdrop-blur-sm shadow-xs">
                        <tr class="border-b border-border-base text-xs font-mono text-secondary uppercase tracking-wider font-bold">
                            <th class="px-6 py-3.5 text-left">Mặt hàng &amp; Mã SKU</th>
                            <th class="px-6 py-3.5 text-left">Ngành hàng</th>
                            <th class="px-6 py-3.5 text-right">Tuổi tồn</th>
                            <th class="px-6 py-3.5 text-right">Tồn kho / Vốn kẹt</th>
                            <th class="px-6 py-3.5 text-right">Vận tốc bán</th>
                            <th class="px-6 py-3.5 text-right">Thao tác</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-border-base text-xs font-mono">
                        <tr ng-repeat="item in $ctrl.getFilteredSkus()" class="even:bg-gray-50/50 hover:bg-blue-50/40 transition-colors">
                            <!-- Text: Left aligned -->
                            <td class="px-6 py-3 text-left">
                                <div class="font-sans font-bold text-primary max-w-[220px] truncate" title="{{ item.name }}">{{ item.name }}</div>
                                <div class="text-[10px] text-secondary mt-0.5">SKU: {{ item.sku }} | Nhập: {{ item.lastRecordDate }}</div>
                            </td>
                            <td class="px-6 py-3 text-left">
                                <span class="px-2 py-0.5 rounded text-[10px] font-bold shadow-xs" 
                                      ng-class="{
                                          'bg-red-50 text-danger border border-danger/20': item.industryContext.industryCode === 'FMCG_FOOD',
                                          'bg-blue-50 text-accent border border-accent/20': item.industryContext.industryCode === 'FASHION_FAST',
                                          'bg-indigo-50 text-indigo-600 border border-indigo-200': item.industryContext.industryCode === 'ELECTRONICS_TECH',
                                          'bg-amber-50 text-amber-600 border border-amber-200': item.industryContext.industryCode === 'HOME_LIVING',
                                          'bg-gray-100 text-secondary border border-gray-200': item.industryContext.industryCode === 'GENERAL'
                                      }">
                                    {{ item.industryContext.displayName }}
                                </span>
                            </td>
                            <!-- Numbers: Right aligned -->
                            <td class="px-6 py-3 text-right font-bold tabular-nums">
                                <span ng-class="{'text-danger': item.daysInInventory > 90, 'text-warn': item.daysInInventory > 60, 'text-primary': item.daysInInventory <= 60}">
                                    {{ item.daysInInventory }} ngày
                                </span>
                            </td>
                            <td class="px-6 py-3 text-right tabular-nums">
                                <div class="text-primary font-bold">{{ item.quantity }} đv</div>
                                <div class="text-secondary text-[10px] mt-0.5">{{ $ctrl.formatVND(item.totalValue) }}</div>
                                <div class="text-danger text-[10px] mt-0.5 font-semibold" title="Chi phí chìm lũy kế">Chìm: {{ $ctrl.formatVND(item.accumulatedSunkCost) }} ({{ $ctrl.getSunkCostRatio(item.accumulatedSunkCost, item.totalValue) }}%)</div>
                            </td>
                            <td class="px-6 py-3 text-right tabular-nums">
                                <span ng-class="{'text-danger font-bold': item.velocities.seasonal == 0, 'text-accent font-black': item.velocities.seasonal > 0}">
                                    {{ item.velocities.seasonal }} đv/ngày
                                </span>
                                <div ng-if="item.velocities.simple == 0 && item.velocities.weighted == 0 && item.velocities.seasonal == 0" 
                                     class="text-[9px] bg-red-100 text-danger mt-1 rounded px-1.5 py-0.5 font-bold inline-block ml-auto shadow-xs uppercase">
                                    ĐÓNG BĂNG
                                </div>
                            </td>
                            <td class="px-6 py-3 text-right">
                                <button ng-if="item.daysInInventory > 60 || item.velocities.seasonal == 0" 
                                        class="bg-accent text-white hover:bg-blue-600 px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all whitespace-nowrap shadow-xs active:scale-[0.98]" 
                                        ng-click="$ctrl.triggerCopilot(item)">
                                    Đề xuất Xả hàng →
                                </button>
                                <span ng-if="item.daysInInventory <= 60 && item.velocities.seasonal > 0" class="text-[10px] text-secondary font-mono italic">An toàn</span>
                            </td>
                        </tr>
                        <tr ng-if="$ctrl.getFilteredSkus().length === 0">
                            <td colspan="6" class="px-6 py-12 text-center text-secondary italic">Không có sản phẩm nào thuộc bộ lọc này.</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

    </div>
</div>
    `,
        controller: [function () {
            var ctrl = this;

            ctrl.bucketFilter = 'all';

            ctrl.setBucketFilter = function (filter: string) {
                ctrl.bucketFilter = filter;
            };

            ctrl.getAllSkusCount = function () {
                if (!ctrl.data) return 0;
                return (ctrl.data.healthySkus || []).length +
                    (ctrl.data.watchlistSkus || []).length +
                    (ctrl.data.slowMovingSkus || []).length +
                    (ctrl.data.deadStockSkus || []).length;
            };

            ctrl.getFilteredSkus = function () {
                if (!ctrl.data) return [];

                var all: any[] = [];

                if (ctrl.bucketFilter === 'all') {
                    all = all.concat(ctrl.data.healthySkus || []);
                    all = all.concat(ctrl.data.watchlistSkus || []);
                    all = all.concat(ctrl.data.slowMovingSkus || []);
                    all = all.concat(ctrl.data.deadStockSkus || []);
                } else if (ctrl.bucketFilter === 'DEAD_STOCK') {
                    all = ctrl.data.deadStockSkus || [];
                } else if (ctrl.bucketFilter === 'SLOW_MOVING') {
                    all = ctrl.data.slowMovingSkus || [];
                }

                // Sort by total value descending
                return all.sort(function (x: any, y: any) {
                    return (y.totalValue || 0) - (x.totalValue || 0);
                });
            };

            ctrl.formatVND = function (value: number) {
                if (!value) return "0 ₫";
                return Math.round(value).toLocaleString('vi-VN') + ' ₫';
            };

            ctrl.getBarWidth = function (value: number) {
                if (!ctrl.data) return 0;
                var total = (ctrl.data.totalHealthyValue || 0) +
                    (ctrl.data.totalWatchlistValue || 0) +
                    (ctrl.data.totalSlowMovingValue || 0) +
                    (ctrl.data.totalDeadStockValue || 0);
                if (!total) return 0;
                return (value / total) * 100;
            };

            ctrl.getSunkCostRatio = function(sunk: number, total: number) {
                if (!total || total <= 0) return 0;
                var ratio = (sunk / total) * 100;
                return Math.min(100, Math.round(ratio * 10) / 10);
            };

            ctrl.getDaysToDeplete = function(quantity: number, velocity: number) {
                if (!velocity || velocity <= 0) return '∞';
                return Math.ceil(quantity / velocity);
            };

            ctrl.triggerCopilot = function(item: any) {
                if (ctrl.onTriggerCopilot) {
                    ctrl.onTriggerCopilot({ item: item });
                }
            };
        }]
    });
