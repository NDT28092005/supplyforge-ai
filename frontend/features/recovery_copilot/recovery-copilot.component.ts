declare var angular: any;

angular.module('supplyForgeApp')
.component('recoveryCopilot', {
    bindings: {
        cluster: '<'
    },
    template: `
<div class="space-y-12">
    <!-- Main Header -->
    <div class="mb-12">
        <span class="text-xs font-mono text-accent tracking-widest uppercase font-bold">
            AI Recovery Copilot · Đang mở chiến dịch
        </span>
        <h2 class="font-tight font-black text-primary text-4xl sm:text-5xl tracking-tightest leading-tight mt-4">
            Giải phóng dòng tiền:
            <br />
            <span class="text-accent">{{ $ctrl.cluster.clusterName || 'Chiến dịch tổng hợp' }}</span>
        </h2>
        <p class="text-secondary text-sm mt-3 max-w-2xl leading-relaxed">
            AI gợi ý chiến lược tối ưu dòng tiền, giảm giá trị sổ sách, và kích hoạt lá chắn thuế phù hợp với tính chất ngành hàng.
        </p>
    </div>

    <!-- Interactive CFO Simulator Panel -->
    <div class="bg-surface border border-border-base rounded-3xl p-6 sm:p-8 space-y-6 shadow-material">
        <div class="text-xs font-mono text-accent uppercase tracking-widest pb-3 border-b border-border-base flex justify-between items-center font-bold">
            <span>Trình giả lập tài chính CFO (Interactive Simulator)</span>
            <span class="bg-blue-50 text-accent border border-accent/20 px-2 py-0.5 rounded text-[10px]">Tải thời gian thực</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            <!-- Left: Simulator Controls -->
            <div class="space-y-6 bg-gray-50/70 p-6 rounded-2xl border border-border-base">
                <h4 class="text-sm font-bold text-primary font-tight">Thông số giả lập xả hàng</h4>
                
                <!-- Discount Slider -->
                <div class="space-y-2">
                    <div class="flex justify-between text-xs font-mono">
                        <span class="text-secondary">Tỷ lệ giảm giá:</span>
                        <span class="text-accent font-bold">{{ $ctrl.simulator.discountPct }}%</span>
                    </div>
                    <input type="range" min="0" max="100" step="5" 
                           ng-model="$ctrl.simulator.discountPct" 
                           ng-change="$ctrl.runSimulation()"
                           class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-accent" />
                    <div class="flex justify-between text-[10px] text-secondary font-mono">
                        <span>0% (Bán nguyên giá)</span>
                        <span>100% (Cho tặng)</span>
                    </div>
                </div>

                <!-- Accounting Method Select -->
                <div class="space-y-2">
                    <div class="text-xs font-mono text-secondary font-semibold">Phương pháp hạch toán tồn kho:</div>
                    <select ng-model="$ctrl.simulator.accounting" 
                            ng-change="$ctrl.runSimulation()"
                            class="w-full bg-surface border border-border-base rounded-xl px-4 py-3 text-xs text-primary font-mono outline-none focus:border-accent shadow-xs">
                        <option value="FIFO">FIFO (Nhập trước Xuất trước)</option>
                        <option value="LIFO">LIFO (Nhập sau Xuất trước) — Lá chắn thuế cao</option>
                    </select>
                    <p class="text-[10px] text-secondary leading-relaxed font-mono mt-1">
                        LIFO ghi nhận giá vốn hàng mới nhất để tăng chi phí hợp lý, qua đó giảm thuế TNDN hiệu quả.
                    </p>
                </div>
            </div>

            <!-- Right/Middle: Financial ROI Output -->
            <div class="md:col-span-2 space-y-6">
                <!-- Simulation Loading indicator -->
                <div ng-if="$ctrl.simLoading" class="py-12 text-center text-accent font-mono animate-pulse">
                    Đang tính toán các chỉ số ROI & Tax Shield...
                </div>

                <!-- Simulation Result Grid -->
                <div ng-if="!$ctrl.simLoading && $ctrl.simResult" class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <!-- Expected Revenue Card -->
                    <div class="bg-surface border border-border-base p-5 rounded-2xl shadow-sm">
                        <div class="text-[10px] font-mono text-secondary uppercase tracking-wider mb-1 font-semibold">Doanh thu dự thu (Net Revenue)</div>
                        <div class="font-tight font-black text-xl text-primary font-mono">{{ $ctrl.formatVND($ctrl.simResult.expectedRevenue - $ctrl.simResult.marketingAndShippingCost) }}</div>
                        <div class="text-[10px] text-secondary mt-1 font-mono">Đã trừ {{ $ctrl.simulator.discountPct }}% chiết khấu & chi phí marketing</div>
                    </div>

                    <!-- Net Recovery Rate Card -->
                    <div class="bg-surface border p-5 rounded-2xl shadow-sm" 
                         ng-class="{'border-danger/30 bg-danger/5': $ctrl.simResult.netRecoveryRate < 0, 'border-accent/30 bg-blue-50/50': $ctrl.simResult.netRecoveryRate >= 0}">
                        <div class="text-[10px] font-mono text-secondary uppercase tracking-wider mb-1 font-semibold">Tỷ lệ thu hồi ròng (Net Recovery Rate)</div>
                        <div class="font-tight font-black text-xl font-mono" 
                             ng-class="{'text-danger': $ctrl.simResult.netRecoveryRate < 0, 'text-accent': $ctrl.simResult.netRecoveryRate >= 0}">
                            {{ $ctrl.simResult.netRecoveryRate }}%
                        </div>
                        <div class="text-[10px] text-secondary mt-1 font-mono">Dựa trên vốn chìm chôn kho</div>
                    </div>

                    <!-- Tax Shield value Card -->
                    <div class="bg-surface border border-border-base p-5 rounded-2xl sm:col-span-2 flex justify-between items-center shadow-sm">
                        <div>
                            <div class="text-[10px] font-mono text-secondary uppercase tracking-wider mb-1 font-semibold">Giá trị Lá Chắn Thuế (Tax Shield Value)</div>
                            <div class="font-tight font-black text-xl text-success font-mono">{{ $ctrl.formatVND($ctrl.simResult.taxShieldValueVnd) }}</div>
                            <div class="text-[10px] text-secondary mt-1 font-mono">Thuế TNDN 20% giảm trực tiếp từ khoản lỗ thanh lý</div>
                        </div>
                        <span ng-if="$ctrl.simResult.taxShieldRecommended" 
                              class="bg-success/10 text-success border border-success/20 text-[10px] font-mono font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg shadow-xs">
                            Khuyên Dùng Tax Shield
                        </span>
                    </div>
                </div>

                <!-- Simulation Recommendation Box -->
                <div ng-if="!$ctrl.simLoading && $ctrl.simResult" class="p-5 rounded-2xl bg-amber-50/60 border border-amber-200/80 space-y-3 shadow-sm">
                    <div class="text-xs font-mono text-amber-800 uppercase tracking-widest font-bold">Khuyến nghị hạch toán & hành động:</div>
                    <p class="text-xs text-primary leading-relaxed">
                        {{ $ctrl.simResult.aiRecommendation }}
                    </p>
                    <p class="text-[11px] text-secondary font-mono leading-relaxed border-t border-amber-200/60 pt-2">
                        {{ $ctrl.simResult.writeOffStrategy }}
                    </p>
                </div>
            </div>
        </div>
    </div>

    <!-- Static CF Matrix Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
        <!-- Financial specs card -->
        <div class="bg-surface border border-border-base rounded-3xl p-6 sm:p-8 space-y-6 shadow-material">
            <div class="text-xs font-mono text-secondary uppercase tracking-widest pb-4 border-b border-border-base font-semibold">
                Chi phí chìm & Dòng tiền đóng băng (Sunk Costs)
            </div>
            <div class="space-y-4">
                <div class="flex justify-between">
                    <span class="text-sm text-secondary">Giá trị vốn ban đầu (Cost Basis)</span>
                    <span class="text-sm text-primary font-mono font-bold">{{ $ctrl.formatVND($ctrl.cluster.totalInitialCost || $ctrl.cluster.totalFrozenValue) }}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-sm text-secondary">Chi phí lưu kho lũy kế</span>
                    <span class="text-sm text-warn font-mono font-bold">{{ $ctrl.formatVND($ctrl.cluster.accumulatedStorageFee || ($ctrl.cluster.totalFrozenValue * 0.05)) }}</span>
                </div>
                <div class="border-t border-border-base pt-4 flex justify-between">
                    <span class="text-sm font-bold text-primary">Tổng chi phí chìm (Sunk Cost)</span>
                    <span class="text-sm text-danger font-mono font-bold">{{ $ctrl.formatVND($ctrl.cluster.totalSunkCost || ($ctrl.cluster.totalFrozenValue * 1.05)) }}</span>
                </div>
            </div>
        </div>

        <!-- Strategy recommendations -->
        <div class="bg-blue-50/40 border border-accent/20 rounded-3xl p-6 sm:p-8 space-y-6 shadow-material">
            <div class="text-xs font-mono text-accent uppercase tracking-widest pb-4 border-b border-accent/10 font-bold">
                Chiến dịch & Kết hợp tiêu thụ (Cross-selling)
            </div>
            <div class="space-y-4">
                <div class="flex justify-between">
                    <span class="text-sm text-secondary">Hành động hàng loạt khuyến nghị</span>
                    <span class="text-sm text-accent font-bold text-right">{{ $ctrl.cluster.recommendedBatchAction || 'Markdown xả hàng lũy tiến' }}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-sm text-secondary">Thời gian xả dự kiến</span>
                    <span class="text-sm text-primary font-mono font-bold">{{ $ctrl.cluster.estimatedClearDays || 14 }} ngày</span>
                </div>
                
                <p ng-if="$ctrl.cluster.bundleAvailable" class="text-xs text-secondary leading-relaxed bg-surface p-4 rounded-xl border border-border-base shadow-xs">
                    <strong class="text-accent">Gợi ý AI Bundle:</strong> Đóng gói các sản phẩm bán chậm trong nhóm này với sản phẩm: <strong class="text-primary">{{ $ctrl.cluster.bundleAvailable.hotItemName }}</strong> (Giá gốc bán lẻ: {{ $ctrl.formatVND($ctrl.cluster.bundleAvailable.hotItemPrice) }}).
                    <br/><span class="text-secondary italic mt-1 inline-block">Cơ sở logic: {{ $ctrl.cluster.bundleAvailable.logic }}</span>
                </p>
            </div>
        </div>
    </div>

    <!-- Items to clean list table -->
    <div class="border border-border-base bg-surface rounded-3xl shadow-material overflow-hidden">
        <div class="px-6 py-4 border-b border-border-base flex items-center justify-between bg-gray-50/50">
            <span class="text-xs font-mono text-primary uppercase tracking-widest font-bold">
                Danh sách sản phẩm thuộc chiến dịch ({{ $ctrl.cluster.items.length || 0 }} SKUs)
            </span>
        </div>

        <div class="divide-y divide-border-base">
            <div ng-repeat="item in $ctrl.cluster.items" class="px-6 py-4 flex items-center justify-between hover:bg-surface-hover transition-colors">
                <div>
                    <div class="text-sm font-bold text-primary">{{ item.skuName }}</div>
                    <div class="text-xs text-secondary font-mono mt-0.5">Thời gian chôn kho: {{ item.agingDays }} ngày</div>
                </div>
                <div class="text-right">
                    <div class="text-sm text-primary font-mono font-semibold">{{ item.stock || 100 }} đơn vị</div>
                </div>
            </div>
            
            <div ng-if="!$ctrl.cluster.items || $ctrl.cluster.items.length === 0" class="px-6 py-12 text-center text-secondary italic">
                Không tìm thấy mẫu sản phẩm trong cụm ưu tiên này.
            </div>
        </div>
    </div>
</div>
    `,
    controller: ['$timeout', 'apiService', function($timeout: any, apiService: any) {
        var ctrl = this;
        
        ctrl.workspaceId = 1;
        ctrl.userId = 'user_default_001';

        ctrl.simulator = {
            discountPct: 35,
            accounting: 'FIFO'
        };

        ctrl.simLoading = false;
        ctrl.simResult = null;

        ctrl.$onInit = function() {
            if (ctrl.cluster && ctrl.cluster.recommendedDiscountPct !== undefined) {
                ctrl.simulator.discountPct = ctrl.cluster.recommendedDiscountPct;
            }
            ctrl.runSimulation();
        };

        ctrl.$onChanges = function(changes: any) {
            if (changes.cluster && changes.cluster.currentValue) {
                if (changes.cluster.currentValue.recommendedDiscountPct !== undefined) {
                    ctrl.simulator.discountPct = changes.cluster.currentValue.recommendedDiscountPct;
                }
                ctrl.runSimulation();
            }
        };

        ctrl.runSimulation = function() {
            ctrl.simLoading = true;
            var discountRatio = ctrl.simulator.discountPct / 100.0;
            var skuId = ctrl.cluster ? (ctrl.cluster.targetSkuId || '') : '';
            var skuName = ctrl.cluster ? (ctrl.cluster.targetSkuName || '') : '';
            
            apiService.getFinancialAnalysis(ctrl.workspaceId, ctrl.userId, discountRatio, ctrl.simulator.accounting, skuId, skuName)
                .then(function(res: any) {
                    if (res.status === 204) {
                        ctrl.simResult = null;
                    } else {
                        ctrl.simResult = res.data;
                    }
                })
                .catch(function(err: any) {
                    console.error("Simulation failed:", err);
                    ctrl.simResult = null;
                })
                .finally(function() {
                    ctrl.simLoading = false;
                });
        };

        ctrl.formatVND = function(value: number) {
            if (!value) return "0 ₫";
            return Math.round(value).toLocaleString('vi-VN') + ' ₫';
        };
    }]
});
