declare var angular: any;

angular.module('supplyForgeApp')
.component('cashflowVault', {
    bindings: {
        data: '<',
        onProceed: '&',
        onRecovery: '&',
        onCommandCenter: '&',
        onImportNew: '&'
    },
    template: `
<div class="space-y-12">
    <!-- Skeleton Loading State -->
    <div ng-if="!$ctrl.data" class="w-full space-y-8 animate-pulse">
        <div class="h-8 bg-gray-200 rounded-lg w-1/3"></div>
        <div class="h-16 bg-gray-200 rounded-2xl w-3/4"></div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div class="h-32 bg-gray-200 rounded-3xl"></div>
            <div class="h-32 bg-gray-200 rounded-3xl"></div>
            <div class="h-32 bg-gray-200 rounded-3xl"></div>
        </div>
        <div class="h-64 bg-gray-200 rounded-3xl"></div>
    </div>

    <div ng-if="$ctrl.data" class="w-full space-y-12">
        
        <!-- Main Header (Loss Aversion Framing) -->
        <div class="mb-12">
            <span class="text-xs font-mono text-danger tracking-widest uppercase font-bold">
                Cảnh báo thất thoát dòng tiền (Loss Aversion)
            </span>
            <h2 class="font-tight font-black tracking-tightest text-primary text-4xl sm:text-6xl leading-tight mt-6 mb-4">
                Kho hàng đang đóng băng
                <br />
                <span class="text-danger tabular-nums">{{ $ctrl.formatVND($ctrl.data.totalDeadStockValueVnd) }}</span>
            </h2>
            <p class="text-secondary text-sm max-w-xl leading-relaxed">
                Số vốn này đang chôn vùi trong {{ $ctrl.data.staleSkuCount }} mặt hàng cũ bán chậm (trên 45 ngày). 
                Ước tính tổn hao chi phí cơ hội là <span class="text-danger font-bold font-mono tabular-nums">{{ $ctrl.formatVND($ctrl.data.estimatedLoss30DaysVnd) }}</span> trong 30 ngày tới.
            </p>
        </div>

        <!-- Strategic KPIs Grid -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-8">
            <div class="border border-border-base bg-surface p-6 rounded-3xl shadow-material">
                <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-2 font-semibold">Vốn Đang Đóng Băng</div>
                <div class="font-tight font-black text-danger text-3xl tabular-nums">{{ $ctrl.formatVND($ctrl.data.totalDeadStockValueVnd) }}</div>
                <div class="text-xs text-secondary mt-1 font-mono">Hàng tồn > 45 ngày</div>
            </div>
            <div class="border border-border-base bg-surface p-6 rounded-3xl shadow-material">
                <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-2 font-semibold">Tổng Vốn Lưu Động Kho</div>
                <div class="font-tight font-black text-primary text-3xl tabular-nums">{{ $ctrl.formatVND($ctrl.data.totalInventoryValueVnd) }}</div>
                <div class="text-xs text-secondary mt-1 font-mono">{{ $ctrl.data.totalRootSkuCount }} SKUs trong cơ sở dữ liệu</div>
            </div>
            <div class="border border-border-base bg-surface p-6 rounded-3xl shadow-material">
                <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-2 font-semibold">Tỷ Lệ Hàng Cần Xử Lý</div>
                <div class="font-tight font-black text-accent text-3xl tabular-nums">
                    {{ (($ctrl.data.totalDeadStockValueVnd / ($ctrl.data.totalInventoryValueVnd || 1)) * 100).toFixed(1) }}%
                </div>
                <div class="text-xs text-secondary mt-1 font-mono">{{ $ctrl.data.staleSkuCount }} SKUs lỗi mùa/chậm</div>
            </div>
        </div>

        <!-- Call to action block -->
        <div class="flex flex-wrap items-center gap-4 mb-12">
            <button ng-click="$ctrl.onCommandCenter()" class="bg-accent text-white font-tight font-bold text-sm px-8 py-4 rounded-2xl hover:bg-blue-600 shadow-material active:scale-[0.98] transition-all flex items-center gap-2">
                <span>🎯 Trợ lý Thu hồi Vốn hàng loạt (Top 3)</span>
            </button>
            <button ng-click="$ctrl.onRecovery()" class="bg-surface border border-border-base text-primary font-tight font-bold text-sm px-8 py-4 rounded-2xl hover:bg-gray-100 shadow-sm active:scale-[0.98] transition-all flex items-center gap-2">
                <span>🕒 Phân tích Tuổi hàng Tồn kho</span>
            </button>
            <button ng-click="$ctrl.onImportNew()" class="bg-red-50 border border-danger/30 text-danger font-tight font-bold text-sm px-8 py-4 rounded-2xl hover:bg-danger hover:text-white active:scale-[0.98] transition-all shadow-xs">
                Xóa &amp; Import mới
            </button>
            <button ng-click="$ctrl.onProceed()" class="text-secondary text-sm hover:text-accent transition-colors font-mono font-semibold ml-auto flex items-center gap-1">
                <span>🔗 Rà soát Mã trùng lặp →</span>
            </button>
        </div>

        <!-- Top Stale SKU List table -->
        <div class="border border-border-base bg-surface rounded-3xl shadow-material overflow-hidden">
            <div class="px-6 py-5 border-b border-border-base flex items-center justify-between bg-gray-50/50">
                <span class="text-xs font-mono text-primary uppercase tracking-widest font-bold">
                    Top 5 SKU Bị Đóng Băng Giá Trị Cao Nhất
                </span>
                <span class="text-xs font-mono text-secondary">
                    Sắp xếp: Vốn đóng băng giảm dần
                </span>
            </div>

            <div class="divide-y divide-border-base text-xs font-mono">
                <div ng-repeat="item in $ctrl.data.topStaleSkus" class="px-6 py-3.5 flex items-center justify-between hover:bg-surface-hover transition-colors even:bg-gray-50/50">
                    <div class="flex items-center gap-4 text-left">
                        <span class="text-secondary text-sm font-semibold opacity-50">{{ $index + 1 }}</span>
                        <div>
                            <div class="text-sm font-bold text-primary font-sans">{{ item.name }}</div>
                            <div class="text-xs text-secondary font-mono mt-0.5">Mã SKU | Nhập gần nhất: {{ item.lastRecordDate }}</div>
                        </div>
                    </div>
                    <div class="text-right tabular-nums">
                        <div class="text-sm font-bold text-danger font-mono">{{ $ctrl.formatVND(item.frozenValueVnd) }}</div>
                        <div class="text-xs text-secondary font-mono mt-0.5">Vốn chôn kho</div>
                    </div>
                </div>
            </div>
        </div>

    </div>
</div>
    `,
    controller: [function() {
        var ctrl = this;

        ctrl.formatVND = function(value: number) {
            if (!value) return "0 ₫";
            return Math.round(value).toLocaleString('vi-VN') + ' ₫';
        };
    }]
});
