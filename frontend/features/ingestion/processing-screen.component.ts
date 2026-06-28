declare var angular: any;

angular.module('supplyForgeApp')
.component('processingScreen', {
    bindings: {
        file: '<',
        onMappingReady: '&'
    },
    template: `
<div class="min-h-screen bg-background flex flex-col items-center justify-center px-6">
    <div class="w-full max-w-md">
        <p class="text-xs font-mono text-secondary tracking-widest uppercase mb-12 text-center opacity-50">
            SupplyForge AI · Đang xử lý
        </p>

        <div class="w-full bg-surface border border-border-base rounded-full h-px mb-8 overflow-hidden">
            <div class="bg-accent h-px rounded-full transition-all duration-500" ng-style="{ width: $ctrl.progress + '%' }"></div>
        </div>

        <div class="space-y-3">
            <div ng-repeat="step in $ctrl.steps" 
                 class="flex items-center gap-3 transition-all duration-500"
                 ng-class="{ 'opacity-30': $index < $ctrl.stepIndex, 'opacity-100': $index === $ctrl.stepIndex, 'opacity-10': $index > $ctrl.stepIndex }">
                <div class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                     ng-class="{ 'bg-primary': $index < $ctrl.stepIndex, 'bg-accent': $index === $ctrl.stepIndex, 'bg-border-base': $index > $ctrl.stepIndex }">
                </div>
                <span class="text-sm font-mono" ng-class="{ 'text-primary': $index === $ctrl.stepIndex, 'text-secondary': $index !== $ctrl.stepIndex }">
                    {{ step.label }}
                    <span ng-if="$index === $ctrl.stepIndex" class="animate-blink text-accent ml-1">▋</span>
                </span>
            </div>
        </div>

        <div class="mt-10 text-right">
            <span class="font-tight font-black text-2xl tracking-tightest text-accent">
                {{ $ctrl.progress }}%
            </span>
        </div>
    </div>
</div>
    `,
    controller: ['$timeout', 'apiService', function($timeout: any, apiService: any) {
        var ctrl = this;
        
        ctrl.progress = 10;
        ctrl.stepIndex = 0;
        ctrl.steps = [
            { label: 'Đang tải file lên server...', duration: 500 },
            { label: 'Mapping cột dữ liệu bằng Gemini...', duration: 800 },
            { label: 'Phân tích dòng tiền và tồn kho...', duration: 1000 },
            { label: 'Kiểm tra SKU trùng lặp...', duration: 700 },
            { label: 'Hoàn tất báo cáo...', duration: 500 }
        ];

        ctrl.$onInit = function() {
            ctrl.runAnalysis();
        };

        ctrl.runAnalysis = function() {
            if (!ctrl.file) {
                // Fallback demo sequence
                $timeout(function() {
                    ctrl.progress = 40;
                    ctrl.stepIndex = 1;
                    $timeout(function() {
                        ctrl.progress = 75;
                        ctrl.stepIndex = 2;
                        $timeout(function() {
                            ctrl.progress = 100;
                            ctrl.stepIndex = 4;
                            $timeout(function() {
                                ctrl.onMappingReady({ data: null });
                            }, 500);
                        }, 800);
                    }, 1000);
                }, 800);
            } else {
                // Real file analysis call
            apiService.analyzeFile(ctrl.file).then(function(res: any) {
                console.log("Analyze file API success. Response:", res);
                ctrl.progress = 80;
                ctrl.stepIndex = 2;
                
                $timeout(function() {
                    ctrl.progress = 100;
                    ctrl.stepIndex = 4;
                    console.log("Progress 100%, preparing to call onMappingReady in 500ms");
                    $timeout(function() {
                        console.log("Calling onMappingReady with data:", res.data);
                        ctrl.onMappingReady({ data: res.data });
                    }, 500);
                }, 800);
            }).catch(function(err: any) {
                console.error('Lỗi phân tích file', err);
                alert("Phân tích file thất bại: " + (err.data && err.data.error ? err.data.error : err.statusText));
                window.location.reload();
            });
            }
        };
    }]
});
