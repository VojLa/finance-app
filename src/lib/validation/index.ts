export type ValidationResult<T> = { success: true; data: T } | { success: false; errors: string[] }

export function validationSuccess<T>(data: T): ValidationResult<T> {
  return { success: true, data }
}

export function validationFailure(errors: string[]): ValidationResult<never> {
  return { success: false, errors }
}
