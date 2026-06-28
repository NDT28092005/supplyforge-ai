declare var angular: any;

angular.module('supplyForgeApp')
.component('trustTheaterHero', {
    bindings: {
        onUpload: '&'
    },
    template: `
<section class="min-h-screen bg-background flex flex-col justify-center px-6 md:px-16 lg:px-24 py-16">
    <div class="max-w-3xl mx-auto w-full">
        <!-- Main Header -->
        <div class="mb-16">
            <span class="text-xs font-mono text-accent tracking-widest uppercase font-bold">
                SupplyForge OS · Trust Theater v0.1
            </span>
            <h1 class="font-tight font-black tracking-tightest text-primary text-5xl sm:text-7xl leading-none mt-6 mb-6">
                Khơi thông dòng tiền
                <br />
                <span class="text-secondary opacity-60">trong kho hàng E-com.</span>
            </h1>
            <p class="text-secondary text-base max-w-xl leading-relaxed">
                Hệ thống tự động phát hiện tồn kho chết (Dead Stock), gom cụm SKU trùng lắp đa sàn và đề xuất phương án giải phóng kho cấp tài chính CFO.
            </p>
        </div>

        <!-- Terminal Simulator Upload Box -->
        <div class="bg-surface border border-border-base shadow-material-lg rounded-3xl p-8 relative overflow-hidden transition-all">
            <div class="flex items-center justify-between mb-8 pb-4 border-b border-border-base">
                <div class="flex gap-2">
                    <div class="w-3 h-3 rounded-full bg-red-400/80"></div>
                    <div class="w-3 h-3 rounded-full bg-warn/80"></div>
                    <div class="w-3 h-3 rounded-full bg-success/80"></div>
                </div>
                <span class="text-xs font-mono text-secondary uppercase tracking-widest font-semibold">
                    Secure Streaming Ingestion
                </span>
            </div>

            <!-- Upload State -->
            <div ng-if="!$ctrl.localFile" class="flex flex-col items-center justify-center py-14 border-2 border-dashed border-border-base rounded-2xl hover:border-accent hover:bg-accent/5 transition-all relative cursor-pointer group">
                <input type="file" file-model="$ctrl.localFile" class="absolute inset-0 opacity-0 cursor-pointer" accept=".csv" />
                <div class="w-14 h-14 rounded-full bg-accent/10 flex items-center justify-center text-accent mb-4 group-hover:scale-110 transition-transform">
                    <span class="text-2xl font-bold">↑</span>
                </div>
                <p class="text-base font-bold text-primary mb-1">
                    Kéo thả hoặc nhấp để tải tệp CSV
                </p>
                <p class="text-xs text-secondary font-mono">
                    Hỗ trợ tệp CSV bán hàng / kho hàng lớn
                </p>
            </div>

            <!-- File Selected State -->
            <div ng-if="$ctrl.localFile" class="py-6 flex flex-col gap-6">
                <div class="flex items-center justify-between bg-background p-5 rounded-2xl border border-border-base shadow-sm">
                    <div class="flex items-center gap-4">
                        <span class="text-3xl">📄</span>
                        <div>
                            <div class="text-sm font-bold text-primary max-w-[200px] sm:max-w-[400px] truncate">{{ $ctrl.localFile.name }}</div>
                            <div class="text-xs font-mono text-secondary mt-0.5">{{ ($ctrl.localFile.size / 1024).toFixed(1) }} KB</div>
                        </div>
                    </div>
                    <button ng-click="$ctrl.removeFile()" class="text-secondary hover:text-danger text-xs font-bold uppercase tracking-wider transition-colors">
                        Gỡ bỏ
                    </button>
                </div>
                
                <button ng-click="$ctrl.upload()" class="w-full bg-accent text-white font-tight font-bold text-base py-4 rounded-2xl hover:bg-blue-600 shadow-material active:scale-[0.99] transition-all">
                    Bắt đầu phân tích tệp →
                </button>
            </div>
        </div>

        <!-- Footer disclaimer -->
        <div class="mt-8 text-center sm:text-left text-xs font-mono text-secondary/60 flex flex-wrap gap-x-6 gap-y-2">
            <span>O(1) Memory Engine</span>
            <span>•</span>
            <span>Gemini AI Columns Mapper</span>
            <span>•</span>
            <span>MySQL Storage</span>
        </div>
    </div>
</section>
    `,
    controller: [function() {
        var ctrl = this;
        ctrl.localFile = null;

        ctrl.fileSelected = function() {
            // Handled via fileModel directive change
        };

        ctrl.removeFile = function() {
            ctrl.localFile = null;
        };

        ctrl.upload = function() {
            if (ctrl.localFile) {
                ctrl.onUpload({ file: ctrl.localFile });
            }
        };
    }]
});
