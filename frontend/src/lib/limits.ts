/** Server-side size limits, mirrored on the inputs so a child can't type past them and get a
 *  rejected answer. (The server stays the authority: 413/422 still map to "that's too long".) */

/** One free-text answer (short answer, a fill-in blank, a typed number). */
export const MAX_FREE_TEXT_CHARS = 2000

/** The learning prompt on the home screen (backend `max_prompt_chars`). */
export const MAX_PROMPT_CHARS = 2000
