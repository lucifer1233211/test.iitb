'use client'

export default function GcsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">GCS</h1>
        <p className="text-gray-500 dark:text-gray-400">Ground Control Station</p>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
        <iframe
          src="http://localhost:3000"
          title="GCS"
          allow="fullscreen; camera; microphone; autoplay"
          allowFullScreen
          className="h-[calc(100vh-210px)] min-h-[720px] w-full"
        />
      </div>
    </div>
  )
}
