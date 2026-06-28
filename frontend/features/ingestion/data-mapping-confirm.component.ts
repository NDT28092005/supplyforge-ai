declare var angular: any;
console.log("data-mapping-confirm.component.js HAS BEEN LOADED AND EXECUTED BY BROWSER!");

angular.module('supplyForgeApp')
.component('dataMappingConfirm', {
    bindings: {
        headers: '<',
        sampleData: '<',
        aiSuggestions: '<',
        onConfirm: '&'
    },
    template: `
<div class="min-h-screen bg-background flex flex-col justify-center px-6 md:px-16 lg:px-24 py-16">
    <div class="max-w-3xl mx-auto w-full">
        <!-- Header -->
        <div class="mb-12">
            <p class="text-xs font-mono text-accent tracking-widest uppercase mb-4 opacity-85">
                Bước 3: AI Column Mapping
            </p>
            <h2 class="font-tight font-black text-primary text-4xl sm:text-5xl tracking-tightest leading-tight">
                Xác nhận ánh xạ trường dữ liệu.
            </h2>
            <p class="text-secondary text-sm mt-3 max-w-xl">
                AI đã đề xuất ánh xạ các cột từ file của bạn. Vui lòng kiểm tra lại sự chuẩn xác bên dưới để bắt đầu nạp cơ sở dữ liệu.
            </p>
        </div>

        <!-- Form mapping card -->
        <div class="bg-surface border border-border-base rounded-2xl p-6 sm:p-8 space-y-6">
            <div class="text-xs font-mono text-secondary/30 uppercase tracking-widest pb-4 border-b border-[#1c1c1c]">
                Ánh xạ trường cơ sở dữ liệu (Database Mapping)
            </div>

            <div class="space-y-4">
                <!-- Field rows loop -->
                <div ng-repeat="field in $ctrl.fields" class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl border border-border-base bg-[#0e0e0e] hover:bg-[#121212] transition-colors">
                    <div>
                        <div class="text-sm font-bold text-primary">{{ field.label }}</div>
                        <div class="text-xs text-secondary/60 mt-0.5">{{ field.desc }}</div>
                    </div>
                    <div class="flex items-center gap-4">
                        <!-- Sample preview value from CSV -->
                        <span ng-if="$ctrl.sampleData" class="text-xs font-mono text-secondary/40 max-w-[150px] truncate" title="Mẫu: {{ $ctrl.getSampleValue(field.key) }}">
                            Mẫu: {{ $ctrl.getSampleValue(field.key) || '—' }}
                        </span>
                        <!-- Column selector select box -->
                        <select ng-model="$ctrl.finalMapping[field.key]" 
                                ng-change="$ctrl.updateMapping(field.key)"
                                class="bg-surface border border-border-base rounded px-3 py-2 text-xs text-primary font-mono outline-none focus:border-accent">
                            <option value="">-- Bỏ qua cột --</option>
                            <option ng-repeat="h in $ctrl.headers" value="{{ h }}">{{ h }}</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- Confirm button -->
            <div class="pt-6 border-t border-[#1c1c1c] flex items-center justify-between">
                <span class="text-xs font-mono text-accent">
                    AI Confidence: {{ $ctrl.aiSuggestions.confidence || 'Medium' }}
                </span>
                <button ng-click="$ctrl.confirm()" class="bg-accent text-background font-tight font-black text-xs px-8 py-3.5 rounded-xl hover:bg-[#deff5a] active:scale-[0.98] transition-all">
                    Đồng ý & Nạp dữ liệu →
                </button>
            </div>
        </div>
    </div>
</div>
    `,
    controller: [function() {
        console.log("dataMappingConfirm component controller instantiated!");
        var ctrl = this;

        // DB Core columns to map
        ctrl.fields = [
            { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc nhãn hiệu của SKU' },
            { key: 'itemSku', label: 'Mã SKU', desc: 'Mã vạch hoặc mã ký tự SKU định danh' },
            { key: 'price', label: 'Giá bán', desc: 'Giá niêm yết bán lẻ cho người tiêu dùng' },
            { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng' },
            { key: 'stock', label: 'Tồn kho', desc: 'Số lượng đơn vị còn tồn kho' },
            { key: 'orderDate', label: 'Ngày ghi nhận', desc: 'Ngày nhập kho hoặc ngày giao dịch gần nhất' }
        ];

        ctrl.finalMapping = {};

        ctrl.$onInit = function() {
            console.log("dataMappingConfirm $onInit called with bindings:", {
                headers: ctrl.headers,
                sampleData: ctrl.sampleData,
                aiSuggestions: ctrl.aiSuggestions
            });
            // Apply suggestions from AI response
            if (ctrl.aiSuggestions && ctrl.headers) {
                var mappingKeys = {
                    productName: 'product_name',
                    itemSku: 'item_sku',
                    price: 'price',
                    cost: 'cost',
                    stock: 'stock',
                    orderDate: 'date'
                };

                angular.forEach(mappingKeys, function(sugKey: string, dbKey: string) {
                    var columnName = ctrl.aiSuggestions[sugKey];
                    if (columnName && ctrl.headers.indexOf(columnName) !== -1) {
                        ctrl.finalMapping[dbKey] = columnName;
                    }
                });

                // Fallbacks if mapping is not fully populated
                if (!ctrl.finalMapping['productName'] && ctrl.headers.length > 0) {
                    ctrl.finalMapping['productName'] = ctrl.headers[0];
                }
                if (!ctrl.finalMapping['itemSku'] && ctrl.headers.length > 0) {
                    ctrl.finalMapping['itemSku'] = ctrl.headers[0];
                }
            }
        };

        ctrl.getSampleValue = function(fieldKey: string) {
            if (!ctrl.sampleData || !ctrl.headers) return null;
            var header = ctrl.finalMapping[fieldKey];
            if (!header) return null;
            var idx = ctrl.headers.indexOf(header);
            return idx >= 0 && idx < ctrl.sampleData.length ? ctrl.sampleData[idx] : null;
        };

        ctrl.updateMapping = function(fieldKey: string) {
            // Trigger recalculation if selector changes
        };

        ctrl.confirm = function() {
            ctrl.onConfirm({ finalMapping: ctrl.finalMapping });
        };
    }]
});
