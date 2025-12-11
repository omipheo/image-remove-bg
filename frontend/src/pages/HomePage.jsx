import { useState } from 'react'
import { useImageProcessing } from '../hooks/useImageProcessing'
import { filterImageFiles } from '../utils/fileUtils'

import UploadSection from '../components/UploadSection'
import OptionsSection from '../components/OptionsSection'
import ImageComparison from '../components/ImageComparison'
import MultipleImagesGrid from '../components/MultipleImagesGrid'
import ErrorMessage from '../components/ErrorMessage'
import DebugPanel from '../components/DebugPanel'

import '../styles/pages/HomePage.css'

const HomePage = () => {
  const [fileType, setFileType] = useState('JPEG')
  const [backgroundColor, setBackgroundColor] = useState('white')
  const [downloadMethod, setDownloadMethod] = useState('zip')
  const [watermark, setWatermark] = useState('blog')
  const [downloadMode, setDownloadMode] = useState('manual')

  const handleDownloadModeChange = (mode) => {
    setDownloadMode(mode)
    if (mode === 'automatic') {
      setDownloadMethod('zip')
    }
  }

  const {
    imageUrl,
    originalImageUrl,
    currentFile,
    isLoading,
    error,
    processedImages,
    processImage,
    processMultipleImages,
    downloadImage,
    downloadProcessedImage,
    downloadAllProcessedImages,
    stopProcessing,
    setError
  } = useImageProcessing()

  const handleFilesSelected = (files) => {
    const imageFiles = filterImageFiles(files)

    if (imageFiles.length === 0) {
      setError('Please select at least one image file')
      return
    }

    // 🔴 CRITICAL FIX:
    // Single image → processImage
    // Multiple images → processMultipleImages
    if (imageFiles.length === 1) {
      processImage(
        imageFiles[0],
        backgroundColor,
        fileType,
        watermark,
        downloadMode
      )
    } else {
      processMultipleImages(
        imageFiles,
        backgroundColor,
        fileType,
        watermark,
        downloadMode
      )
    }
  }

  const hasBatchImages = processedImages && processedImages.length > 0
  const showSingleImageComparison =
    currentFile && !hasBatchImages

  return (
    <div className="container">
      <h1>Background Removal Tool</h1>

      <UploadSection
        onFilesSelected={handleFilesSelected}
        isLoading={isLoading}
        onDownloadAll={() =>
          downloadAllProcessedImages(fileType, downloadMethod === 'zip')
        }
        hasProcessedImages={!!(imageUrl || hasBatchImages)}
        onStop={stopProcessing}
        showDownload={downloadMode === 'manual'}
      />

      <OptionsSection
        fileType={fileType}
        backgroundColor={backgroundColor}
        downloadMethod={downloadMethod}
        watermark={watermark}
        downloadMode={downloadMode}
        onFileTypeChange={setFileType}
        onBackgroundColorChange={setBackgroundColor}
        onDownloadMethodChange={setDownloadMethod}
        onWatermarkChange={setWatermark}
        onDownloadModeChange={handleDownloadModeChange}
        isLoading={isLoading}
      />

      <ErrorMessage
        error={error}
        onDismiss={() => setError(null)}
      />

      {/* ✅ SINGLE IMAGE VIEW ONLY */}
      {showSingleImageComparison && (
        <ImageComparison
          originalImageUrl={originalImageUrl}
          processedImageUrl={imageUrl}
          currentFile={currentFile}
          onDownload={() => downloadImage(fileType)}
          isLoading={isLoading}
          showDownload={downloadMode === 'manual'}
        />
      )}

      {/* ✅ MULTIPLE IMAGES GRID ONLY */}
      {hasBatchImages && (
        <MultipleImagesGrid
          processedImages={processedImages}
          onDownload={downloadProcessedImage}
          fileType={fileType}
          isLoading={isLoading}
          showDownload={downloadMode === 'manual'}
        />
      )}

      <DebugPanel frontendProcessedImages={processedImages} />
    </div>
  )
}

export default HomePage
