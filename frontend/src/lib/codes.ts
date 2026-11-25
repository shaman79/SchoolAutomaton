/**
 * The two kinds of code a person may type: a learner's own resume code (8 characters, `K7QF-2M9X`,
 * learns as that child) and a parent code (10 characters, `ABCDE-FGHJK`, only follows them). They
 * differ in length on purpose, so a screen can tell which one it was given and say what to do with
 * the other one instead of answering "unknown code".
 */

export const RESUME_CODE_LEN = 8
export const PARENT_CODE_LEN = 10

/** Compare codes the way the server does (case, dashes/spaces and look-alike letters ignored). */
export function normalizeCode(code: string): string {
  return code
    .trim()
    .toUpperCase()
    .replace(/[\s-]/g, '')
    .replace(/[IL]/g, '1')
    .replace(/O/g, '0')
    .replace(/U/g, 'V')
}

export type CodeKind = 'resume' | 'parent' | 'unknown'

/** Which kind of code this looks like (by its length once normalized). */
export function codeKind(code: string): CodeKind {
  const n = normalizeCode(code)
  if (!/^[0-9A-Z]+$/.test(n)) return 'unknown'
  if (n.length === RESUME_CODE_LEN) return 'resume'
  if (n.length === PARENT_CODE_LEN) return 'parent'
  return 'unknown'
}

/** "abcdefghjk" -> "ABCDE-FGHJK" for display/storage; anything else is kept as typed (uppercased). */
export function formatParentCode(code: string): string {
  const n = normalizeCode(code)
  return n.length === PARENT_CODE_LEN ? `${n.slice(0, 5)}-${n.slice(5)}` : code.trim().toUpperCase()
}
