import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { routes } from './app.routes';
import { AppComponent } from './app.component';
import { HeaderComponent } from './header/header.component';
import { SidebarComponent } from './sidebar/sidebar.component';
import { DashboardComponent } from './dashboard/dashboard.component';
import { TrustTheaterHeroComponent } from './trust-theater-hero/trust-theater-hero.component';
import { DataMappingConfirmComponent } from './data-mapping-confirm/data-mapping-confirm.component';
import { ProcessingScreenComponent } from './processing-screen/processing-screen.component';
import { CashflowVaultComponent } from './cashflow-vault/cashflow-vault.component';
import { InventoryAgingRadarComponent } from './inventory-aging-radar/inventory-aging-radar.component';
import { CommandCenterDashboardComponent } from './command-center-dashboard/command-center-dashboard.component';
import { RecoveryCopilotComponent } from './recovery-copilot/recovery-copilot.component';
import { SkuDeduplicationTinderComponent } from './sku-deduplication-tinder/sku-deduplication-tinder.component';

@NgModule({
  declarations: [
    AppComponent
  ],
  imports: [
    BrowserModule,
    CommonModule,
    HttpClientModule,
    FormsModule,
    RouterModule.forRoot(routes),
    HeaderComponent,
    SidebarComponent,
    DashboardComponent,
    TrustTheaterHeroComponent,
    DataMappingConfirmComponent,
    ProcessingScreenComponent,
    CashflowVaultComponent,
    InventoryAgingRadarComponent,
    CommandCenterDashboardComponent,
    RecoveryCopilotComponent,
    SkuDeduplicationTinderComponent
  ],
  providers: [],
  bootstrap: [AppComponent]
})
export class AppModule { }
