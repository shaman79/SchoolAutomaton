/** Retry an async call a few times with short pauses — for the blips a phone on a bus or a server
 *  mid-deploy produces — but only for failures `shouldRetry` says can heal by waiting. */

export interface RetryOptions {
  /** Pause before each retry, in ms. `[500, 1500]` = up to 3 attempts in total. */
  delays: readonly number[]
  shouldRetry: (e: unknown) => boolean
  /** Injectable for tests. */
  sleep?: (ms: number) => Promise<void>
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export async function withRetry<T>(fn: () => Promise<T>, opts: RetryOptions): Promise<T> {
  const sleep = opts.sleep ?? defaultSleep
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (e) {
      if (attempt >= opts.delays.length || !opts.shouldRetry(e)) throw e
      await sleep(opts.delays[attempt])
    }
  }
}
