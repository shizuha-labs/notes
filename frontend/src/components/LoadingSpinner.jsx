import { Loader2 } from 'lucide-react'
import { cn } from '../utils/cn'

const sizes = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-10 w-10',
}

export default function LoadingSpinner({ size = 'md', className }) {
  return (
    <Loader2 className={cn('animate-spin text-shizuha-600', sizes[size], className)} />
  )
}
