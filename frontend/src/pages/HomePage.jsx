import { useState } from 'react'
import { useImageProcessing } from '../hooks/useImageProcessing'
import { filterImageFiles } from '../utils/fileUtils'
import UploadSection from '../components/UploadSection'
import OptionsSection from '../components/OptionsSection'
import ImageComparison from '../components/ImageComparison'
import MultipleImagesGrid from '../components/MultipleImagesGrid'
import ErrorMessage from '../components/ErrorMessage'
import '../styles/pages/HomePage.css'

const HomePage = () => {
  const [fileType, setFileType] = useState('JPEG')
  const [backgroundColor, setBackgroundColor] = useState('white')
  const [downloadMethod, setDownloadMethod] = useState('zip')
  
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

    if (imageFiles.length === 1) {
      processImage(imageFiles[0], backgroundColor, fileType)
    } else {
      processMultipleImages(imageFiles, backgroundColor, fileType)
    }
  }

  return (
    <div className="container">
      <h1>Background Removal Tool</h1>
      
      <UploadSection 
        onFilesSelected={handleFilesSelected}
        isLoading={isLoading}
        onDownloadAll={() => downloadAllProcessedImages(fileType, downloadMethod === 'zip')}
        hasProcessedImages={!!(imageUrl || (processedImages && processedImages.length > 0))}
        onStop={stopProcessing}
      />

      <OptionsSection
        fileType={fileType}
        backgroundColor={backgroundColor}
        downloadMethod={downloadMethod}
        onFileTypeChange={setFileType}
        onBackgroundColorChange={setBackgroundColor}
        onDownloadMethodChange={setDownloadMethod}
        isLoading={isLoading}
      />

      <ErrorMessage 
        error={error} 
        onDismiss={() => setError(null)}
      />

      <ImageComparison
        originalImageUrl={originalImageUrl}
        processedImageUrl={imageUrl}
        currentFile={currentFile}
        onDownload={() => downloadImage(fileType)}
        isLoading={isLoading}
      />

      <MultipleImagesGrid
        processedImages={processedImages}
        onDownload={downloadProcessedImage}
        fileType={fileType}
        isLoading={isLoading}
      />
    </div>
  )
}

export default HomePage

