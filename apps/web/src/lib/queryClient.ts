import { QueryClient } from '@tanstack/react-query';

/**
 * App-wide query client (SPEC §8.4). Run event streams live outside the
 * query cache in dedicated stores; list queries must not churn on focus.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}
