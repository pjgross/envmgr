import { useSnackbar as useNotistackSnackbar, VariantType } from 'notistack'
import { useCallback } from 'react'

type Message = string

interface AppSnackbar {
    success: (message: Message) => void
    error: (message: Message) => void
    info: (message: Message) => void
    warning: (message: Message) => void
    show: (message: Message, variant?: VariantType) => void
}

export function useSnackbar(): AppSnackbar {
    const { enqueueSnackbar } = useNotistackSnackbar()

    const show = useCallback(
        (message: Message, variant: VariantType = 'default') => {
            enqueueSnackbar(message, { variant })
        },
        [enqueueSnackbar],
    )

    return {
        success: useCallback((m) => enqueueSnackbar(m, { variant: 'success' }), [enqueueSnackbar]),
        error: useCallback((m) => enqueueSnackbar(m, { variant: 'error' }), [enqueueSnackbar]),
        info: useCallback((m) => enqueueSnackbar(m, { variant: 'info' }), [enqueueSnackbar]),
        warning: useCallback((m) => enqueueSnackbar(m, { variant: 'warning' }), [enqueueSnackbar]),
        show,
    }
}
