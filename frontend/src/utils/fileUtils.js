/**
 * Read image file as data URL
 */
export const readImageAsDataURL = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (event) => resolve(event.target.result)
    reader.onerror = () => reject(new Error('Failed to read image file'))
    reader.readAsDataURL(file)
  })
}

/**
 * Download file from blob or data URL
 */
export const downloadFile = (blobOrUrl, filename) => {
  const link = document.createElement('a')
  link.href = typeof blobOrUrl === 'string' ? blobOrUrl : window.URL.createObjectURL(blobOrUrl)
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  
  if (typeof blobOrUrl !== 'string') {
    window.URL.revokeObjectURL(link.href)
  }
}

/**
 * Generate download filename
 */
export const generateDownloadFilename = (originalName, fileType) => {
  const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '')
  const extension = fileType.toLowerCase() === 'jpeg' ? 'jpg' : 'png'
  return `${nameWithoutExt}-no-bg.${extension}`
}

/**
 * Filter image files from file list
 */
export const filterImageFiles = (files) => {
  return Array.from(files).filter(file => file.type.startsWith('image/'))
}

/**
 * Convert blob URL to data URL (for secure display)
 */
export const blobURLToDataURL = async (blobUrl) => {
  try {
    const response = await fetch(blobUrl)
    const blob = await response.blob()
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = () => reject(new Error('Failed to convert blob URL to data URL'))
      reader.readAsDataURL(blob)
    })
  } catch (err) {
    throw new Error(`Failed to convert blob URL: ${err.message}`)
  }
}

/**
 * Convert data URL to blob
 */
export const dataURLToBlob = (dataURL) => {
  const arr = dataURL.split(',')
  const mime = arr[0].match(/:(.*?);/)[1]
  const bstr = atob(arr[1])
  let n = bstr.length
  const u8arr = new Uint8Array(n)
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n)
  }
  return new Blob([u8arr], { type: mime })
}

/**
 * Add PEDALS to METAL.com watermark to an image
 * @param {string} imageDataURL - Data URL of the image
 * @param {string} backgroundColor - Background color: 'white', 'black', or 'transparent'
 * @returns {Promise<string>} - Data URL of the watermarked image
 */
export const addWatermark = (imageDataURL, backgroundColor = 'white') => {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d')
      
      // Set canvas size to match image
      canvas.width = img.width
      canvas.height = img.height
      
      // Draw the original image
      ctx.drawImage(img, 0, 0)
      
      // Calculate watermark size based on image dimensions
      const baseFontSize = Math.max(14, img.width * 0.025) // 2.5% of image width, minimum 14px
      const smallFontSize = Math.max(10, baseFontSize * 0.7) // Smaller font for .com
      
      // Determine watermark color based on background
      // Use dark color for white/transparent backgrounds, white for dark backgrounds
      const bgColor = backgroundColor.toLowerCase()
      const watermarkColor = (bgColor === 'white' || bgColor === 'transparent') ? 'black' : 'white'
      
      // Set font styles
      ctx.font = `bold ${baseFontSize}px Arial, sans-serif`
      ctx.fillStyle = watermarkColor
      ctx.strokeStyle = watermarkColor
      ctx.textAlign = 'left'
      ctx.textBaseline = 'top'
      
      // Text parts
      const mainText = 'PEDALS to METAL'
      const smallText = '.com'
      
      // Measure text
      const mainTextMetrics = ctx.measureText(mainText)
      const mainTextWidth = mainTextMetrics.width
      const mainTextHeight = baseFontSize
      
      ctx.font = `${smallFontSize}px Arial, sans-serif`
      const smallTextMetrics = ctx.measureText(smallText)
      const smallTextWidth = smallTextMetrics.width
      const smallTextHeight = smallFontSize
      
      // Calculate circle dimensions (three circles like pedal knobs)
      const circleRadius = Math.max(6, img.width * 0.01) // 1% of image width, minimum 6px
      const circleSpacing = circleRadius * 2.2 // Space between circles
      const circlesWidth = (circleRadius * 2 * 3) + (circleSpacing * 2) // Total width of three circles
      
      // Rounded rectangle around circles (red section 1)
      const rectPadding = circleRadius * 0.8
      const rectWidth = circlesWidth + (rectPadding * 2)
      const rectHeight = (circleRadius * 2) + (rectPadding * 2)
      const rectRadius = circleRadius * 0.5
      
      // Total watermark width (rect or text, whichever is wider)
      const watermarkWidth = Math.max(rectWidth, mainTextWidth + smallTextWidth)
      const watermarkHeight = rectHeight + 10 + mainTextHeight // Rect + spacing + text
      
      // Position: bottom right with padding
      const padding = Math.max(10, img.width * 0.02) // 2% of image width, minimum 10px
      const watermarkX = img.width - watermarkWidth - padding
      const watermarkY = img.height - watermarkHeight - padding
      
      // Draw rounded rectangle around circles (red section 1)
      const rectX = watermarkX + (watermarkWidth - rectWidth) / 2
      const rectY = watermarkY
      ctx.strokeStyle = watermarkColor
      ctx.lineWidth = 1.5
      // Use roundRect if available, otherwise draw manually
      if (ctx.roundRect) {
        ctx.beginPath()
        ctx.roundRect(rectX, rectY, rectWidth, rectHeight, rectRadius)
        ctx.stroke()
      } else {
        // Fallback: draw rounded rectangle manually
        ctx.beginPath()
        ctx.moveTo(rectX + rectRadius, rectY)
        ctx.lineTo(rectX + rectWidth - rectRadius, rectY)
        ctx.quadraticCurveTo(rectX + rectWidth, rectY, rectX + rectWidth, rectY + rectRadius)
        ctx.lineTo(rectX + rectWidth, rectY + rectHeight - rectRadius)
        ctx.quadraticCurveTo(rectX + rectWidth, rectY + rectHeight, rectX + rectWidth - rectRadius, rectY + rectHeight)
        ctx.lineTo(rectX + rectRadius, rectY + rectHeight)
        ctx.quadraticCurveTo(rectX, rectY + rectHeight, rectX, rectY + rectHeight - rectRadius)
        ctx.lineTo(rectX, rectY + rectRadius)
        ctx.quadraticCurveTo(rectX, rectY, rectX + rectRadius, rectY)
        ctx.closePath()
        ctx.stroke()
      }
      
      // Draw three outlined circles with inner knob design (like pedal knobs) at the top
      ctx.fillStyle = watermarkColor
      ctx.strokeStyle = watermarkColor
      const circleY = watermarkY + rectPadding + circleRadius
      const circleStartX = rectX + rectPadding + circleRadius
      
      for (let i = 0; i < 3; i++) {
        const circleX = circleStartX + (i * (circleRadius * 2 + circleSpacing))
        
        // Draw circle with wavy/scalloped edge (gear-like appearance)
        ctx.beginPath()
        const segments = 16 // Number of segments for wavy edge
        for (let j = 0; j <= segments; j++) {
          const angle = (j / segments) * Math.PI * 2
          const waveOffset = Math.sin(angle * 4) * (circleRadius * 0.1) // Create wavy edge
          const r = circleRadius + waveOffset
          const x = circleX + Math.cos(angle) * r
          const y = circleY + Math.sin(angle) * r
          if (j === 0) {
            ctx.moveTo(x, y)
          } else {
            ctx.lineTo(x, y)
          }
        }
        ctx.closePath()
        ctx.stroke()
        
        // Draw inner knob design: central dot
        ctx.beginPath()
        ctx.arc(circleX, circleY, circleRadius * 0.15, 0, Math.PI * 2)
        ctx.fill()
        
        // Draw inner knob design: pointer line extending from center to edge
        const pointerLength = circleRadius * 0.6
        const pointerAngle = -Math.PI / 2 // Pointing upward (12 o'clock position)
        const pointerEndX = circleX + Math.cos(pointerAngle) * pointerLength
        const pointerEndY = circleY + Math.sin(pointerAngle) * pointerLength
        
        ctx.beginPath()
        ctx.moveTo(circleX, circleY)
        ctx.lineTo(pointerEndX, pointerEndY)
        ctx.stroke()
      }
      
      // Draw text "PEDALS" (red section 2)
      ctx.font = `bold ${baseFontSize}px Arial, sans-serif`
      ctx.fillStyle = 'white'
      const textY = watermarkY + rectHeight + 10
      const textX = watermarkX + (watermarkWidth - mainTextWidth - smallTextWidth) / 2
      
      // Split text to handle "PEDALS", "to", "METAL" separately
      const pedalsText = 'PEDALS'
      const toText = 'to'
      const metalText = 'METAL'
      
      // Measure individual text parts
      const pedalsMetrics = ctx.measureText(pedalsText)
      const pedalsWidth = pedalsMetrics.width
      
      ctx.font = `italic ${baseFontSize * 0.6}px Arial, sans-serif`
      const toMetrics = ctx.measureText(toText)
      const toWidth = toMetrics.width
      
      ctx.font = `bold ${baseFontSize}px Arial, sans-serif`
      const metalMetrics = ctx.measureText(metalText)
      const metalWidth = metalMetrics.width
      
      // Calculate positions
      const pedalsX = textX
      const toX = pedalsX + pedalsWidth + 5
      const metalX = toX + toWidth + 5
      
      // Draw "PEDALS" (red section 2)
      ctx.font = `bold ${baseFontSize}px Arial, sans-serif`
      ctx.fillStyle = watermarkColor
      ctx.fillText(pedalsText, pedalsX, textY)
      
      // Draw "to" (red section 3)
      ctx.font = `italic ${baseFontSize * 0.6}px Arial, sans-serif`
      ctx.fillStyle = watermarkColor
      ctx.fillText(toText, toX, textY + (baseFontSize * 0.2))
      
      // Draw "METAL" (red section 4)
      ctx.font = `bold ${baseFontSize}px Arial, sans-serif`
      ctx.fillStyle = watermarkColor
      ctx.fillText(metalText, metalX, textY)
      
      // Draw ".com" with cloud-like outline (red section 5)
      ctx.font = `${smallFontSize}px Arial, sans-serif`
      const comMetrics = ctx.measureText(smallText)
      const comWidth = comMetrics.width
      const comHeight = smallFontSize
      const comX = metalX + metalWidth + 5
      const comY = textY + (baseFontSize - comHeight) + 2
      
      // Draw cloud-like/star-like outline around ".com"
      const cloudPadding = 3
      const cloudWidth = comWidth + (cloudPadding * 2)
      const cloudHeight = comHeight + (cloudPadding * 2)
      const cloudX = comX - cloudPadding
      const cloudY = comY - cloudPadding
      
      ctx.strokeStyle = watermarkColor
      ctx.lineWidth = 1
      ctx.beginPath()
      // Create irregular cloud-like shape
      const cloudPoints = 8
      for (let i = 0; i <= cloudPoints; i++) {
        const angle = (i / cloudPoints) * Math.PI * 2
        const radiusVariation = 1 + Math.sin(angle * 3) * 0.3 // Create irregular shape
        const r = (Math.min(cloudWidth, cloudHeight) / 2) * radiusVariation
        const x = cloudX + cloudWidth / 2 + Math.cos(angle) * r
        const y = cloudY + cloudHeight / 2 + Math.sin(angle) * r
        if (i === 0) {
          ctx.moveTo(x, y)
        } else {
          ctx.lineTo(x, y)
        }
      }
      ctx.closePath()
      ctx.stroke()
      
      // Draw ".com" text
      ctx.font = `italic ${smallFontSize}px Arial, sans-serif`
      ctx.fillStyle = watermarkColor
      ctx.fillText(smallText, comX, comY)
      
      // Convert canvas to data URL
      const watermarkedDataURL = canvas.toDataURL('image/png')
      resolve(watermarkedDataURL)
    }
    
    img.onerror = () => {
      reject(new Error('Failed to load image for watermarking'))
    }
    
    img.src = imageDataURL
  })
}

