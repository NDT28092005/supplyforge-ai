import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface DashboardState {
  dashboardData: any | null;
  selectedSkuId: string | null;
  hasData: boolean;
}

const initialState: DashboardState = {
  dashboardData: null,
  selectedSkuId: null,
  hasData: false
};

const STORAGE_KEY = 'supplyforge_dashboard_state';

function getPersistedState(): DashboardState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        dashboardData: parsed.dashboardData || null,
        selectedSkuId: parsed.selectedSkuId || null,
        hasData: parsed.hasData ?? false
      };
    }
  } catch (e) {
    console.warn('[DashboardState] Could not load from sessionStorage:', e);
  }
  return initialState;
}

@Injectable({
  providedIn: 'root'
})
export class DashboardStateService {
  private state$ = new BehaviorSubject<DashboardState>(getPersistedState());

  get state(): DashboardState {
    return this.state$.getValue();
  }

  get stateObservable() {
    return this.state$.asObservable();
  }

  private persist(newState: DashboardState) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        dashboardData: newState.dashboardData,
        selectedSkuId: newState.selectedSkuId,
        hasData: newState.hasData
      }));
    } catch (e) {}
    this.state$.next(newState);
  }

  setDashboardData(data: any) {
    this.persist({
      ...this.state,
      dashboardData: data,
      hasData: !!data
    });
  }

  setSelectedSkuId(skuId: string | null) {
    this.persist({ ...this.state, selectedSkuId: skuId });
  }

  setHasData(hasData: boolean) {
    this.persist({ ...this.state, hasData });
  }

  reset() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    this.state$.next(initialState);
  }
}
