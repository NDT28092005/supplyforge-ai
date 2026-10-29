import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ApiService } from '../../api.service';
import { DashboardStateService } from '../state/dashboard-state.service';
import { IngestionStateService } from '../state/ingestion-state.service';
import { map, catchError, of } from 'rxjs';

export const dataReadyGuard: CanActivateFn = (route, state) => {
  const apiService = inject(ApiService);
  const dashboardState = inject(DashboardStateService);
  const ingestionState = inject(IngestionStateService);
  const router = inject(Router);

  if (ingestionState.isDatasetTransitionActive) {
    router.navigate(['/app/import']);
    return false;
  }

  // If we already know data is loaded in state
  if (dashboardState.state.hasData) {
    return true;
  }

  return apiService.checkData().pipe(
    map((res: any) => {
      if (res && res.hasData && !ingestionState.isDatasetTransitionActive) {
        dashboardState.setHasData(true);
        return true;
      }
      router.navigate(['/app/import']);
      return false;
    }),
    catchError(() => {
      router.navigate(['/app/import']);
      return of(false);
    })
  );
};
