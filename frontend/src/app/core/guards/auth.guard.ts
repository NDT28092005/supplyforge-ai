import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';
import { AuthService } from '../../auth.service';

/** Restores an HttpOnly-cookie session before allowing any private route. */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.restoreSession().pipe(
    map((user) => user
      ? true
      : router.createUrlTree(['/auth'], {
          queryParams: { reason: 'session_expired', returnUrl: state.url }
        })
    )
  );
};
