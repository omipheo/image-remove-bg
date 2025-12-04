"""Image storage management for processed images"""
# Store processed images temporarily (in production, use a proper storage solution)
import zipfile
import io
import threading

processed_images = {}
# Progressive ZIP storage: {session_id: {"zip_buffer": BytesIO, "lock": Lock, "image_count": int}}
progressive_zips = {}


def store_image(image_id, image_data, filename, format, mime_type):
    """Store a processed image"""
    processed_images[image_id] = {
        "data": image_data,
        "filename": filename,
        "format": format,
        "mime_type": mime_type
    }


def get_image(image_id):
    """Get a stored image by ID"""
    return processed_images.get(image_id)


def get_latest_image():
    """Get the most recently processed image"""
    if not processed_images:
        return None
    latest_id = list(processed_images.keys())[-1]
    return processed_images[latest_id]


def get_all_images():
    """Get all stored images (for debugging)"""
    return processed_images


def create_or_update_progressive_zip(session_id, image_id, image_data, filename):
    """Create or add to progressive ZIP file for a session"""
    if session_id not in progressive_zips:
        # Create new ZIP for this session
        zip_buffer = io.BytesIO()
        zip_file = zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED)
        progressive_zips[session_id] = {
            "zip_buffer": zip_buffer,
            "zip_file": zip_file,
            "lock": threading.Lock(),
            "image_count": 0
        }
    
    zip_info = progressive_zips[session_id]
    with zip_info["lock"]:
        # Check if ZIP was closed (finalized) - if so, we can't add more
        # This can happen if get_progressive_zip was called (which closes the ZIP)
        # In that case, we skip adding (the ZIP is already finalized for download)
        try:
            # Try to add image to ZIP
            zip_info["zip_file"].writestr(filename, image_data)
            zip_info["image_count"] += 1
        except (ValueError, RuntimeError, AttributeError) as e:
            # ZIP is closed or invalid, can't add more - this is OK if we're done processing
            # The ZIP has already been finalized for download
            print(f"Warning: Cannot add {filename} to finalized ZIP for session {session_id}: {e}")


def get_progressive_zip(session_id):
    """Get the current progressive ZIP file for a session (finalizes and returns a copy)"""
    if session_id not in progressive_zips:
        return None
    
    zip_info = progressive_zips[session_id]
    with zip_info["lock"]:
        # Close the ZIP file to finalize it (writes central directory)
        # This is required for the ZIP to be valid and readable
        zip_info["zip_file"].close()
        
        # Read the finalized ZIP data
        zip_info["zip_buffer"].seek(0)
        zip_data = zip_info["zip_buffer"].read()
        
        # Note: Once closed, we can't add more to this ZIP
        # The ZIP is finalized and ready for download
        # If more images come in after this, they won't be in the ZIP,
        # but typically this is called after all processing is done
        
        return zip_data


def cleanup_progressive_zip(session_id):
    """Clean up progressive ZIP for a session"""
    if session_id in progressive_zips:
        zip_info = progressive_zips[session_id]
        with zip_info["lock"]:
            zip_info["zip_file"].close()
        del progressive_zips[session_id]

