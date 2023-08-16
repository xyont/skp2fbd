#
# CalculiX *.fbd exporter modified by Suyono Nt. 2023
# adapted from GMSH *.geo exporter (Guy Vaessen, 2013)
#
# First we pull in the standard API hooks.
require 'sketchup.rb'

# Define global variables
$pointcounter = 1
$centercounter = 1
$linecounter = 1
$facecounter = 1
$surfcounter = 1
$bodycounter = 1
$unique_points = []
$unique_edges = []
$unique_faces = []
$unique_groups = []
$groups_position = []
$outer_face = []
$output_text = []
$complex_face_index_number = []
$outer_face2 = []
$circle_center = []
$circle_begin = []
$circle_end = []

# Add a menu item to launch our plugin.
UI.menu("PlugIns").add_item("Write CalculiX CGX .fbd file") {
	# Call our main method.
	find_entities
	
}

def find_entities
      model = Sketchup.active_model
      ss = model.selection
      entities = model.entities

      if ss.empty?
         answer = UI.messagebox("No objects selected. Export entire model?", MB_YESNOCANCEL)
         if( answer == 6 )
            export_ents = entities
         else
            export_ents = ss
         end
      else
         export_ents = Sketchup.active_model.selection
      end
      if (export_ents.length > 0)
         write_cgx_fbd_file(export_ents)
      end
end

def write_cgx_fbd_file(export_ents)
	# Write File with Exception Handling
	begin
         	model = Sketchup.active_model
		file_type="fbd"
		#file name
		path_to_save_to = UI.savepanel( file_type.upcase + " file location", "" , "#{File.basename(model.path).split(".")[0]}exp." +file_type )

             	if !path_to_save_to.nil?
                	myFile = File.open(path_to_save_to, 'w')
                	write_header(myFile)
                	
                	Sketchup.status_text="Export started ..."
                	
			# Recursively export groups, faces, edges and text, counting any entities we can't export
			others = find_faces(0, export_ents, Geom::Transformation.new())
			
			Sketchup.status_text="Parsing objects ..."
			
			# Special routine to deal with circles and arc's properly
			#number_of_edge_curves = 16
			#theta = 2.0 * Math::PI / number_of_edge_curves
			#rot_tr = Geom::Transformation.rotation( ORIGIN, Z_AXIS, theta )
			#point = Geom::Point3d.new( 1.0, 0.0, 0.0 ) # pts[0] with radius of unity
			#pts = Array.new
			#number_of_edge_curves.times do
			#	pts << point.clone
			#	point.transform!( rot_tr )
			#end
			#translate = Geom::Transformation.new cp
			#tr_rt = Geom::Transformation.rotation ORIGIN, vec2, -angle
			#scaling = Geom::Transformation.scaling( ORIGIN, scale_factor )
			#pts.map!{|point| point.transform( translate * tr_rt * scaling) }

			# find_circles
			
			# Special routine to deal with color of faces definition
			#my_mat_names = []
			#Sketchup.active_model.materials.each do |mt|
			#  my_mat_names << mt.name
			#end
			#mat_list = my_mat_names.join('|')
			#prompts = ["Material"]
			#defaults = ["white"]
			#list = [mat_list]
			#title = "Material"
			#choice = UI.inputbox( prompts, defaults, list, title )			
            	
                	#Write all found entities to file
                	write_points_to_fbd_file(myFile)
			
			write_lines_to_fbd_file(myFile)
			
			face_index_number = write_faces_to_fbd_file(myFile)
			
			write_volumes_to_fbd_file(myFile,face_index_number)
			
			write_text_to_fbd_file(myFile)
                	
                	myFile.close
                	UI.messagebox( $unique_groups.length.to_s + " volumes exported\n" + $unique_faces.length.to_s + " faces exported\n" + $unique_edges.length.to_s + " lines exported\n" + $unique_points.length.to_s + " points exported\n" + $output_text.length.to_s + " text strings exported\n" + others.to_s + " objects ignored" )
                else
                	UI.messagebox "Failure"
             	end
	rescue => err
		puts "Exception: #{err}"
		err
	end
end

def find_faces(others, entities, tform)
   entities.each do |entity|
    # Check if entity is hidden or deleted
    if (not entity.deleted?) && (not entity.hidden?)
      #Face entity
      if( entity.is_a?(Sketchup::Face) )
       find_edges(entity,tform)
       $unique_faces << entity if not $unique_faces.include?(entity)
      #Edge entity
      elsif( entity.typename == "Edge")
       find_vertices(entity,tform)
      #Group and component:instance entities
      elsif entity.is_a?(Sketchup::Group) || entity.is_a?(Sketchup::ComponentInstance)
       if entity.is_a?(Sketchup::Group)
       	$unique_groups << entity if not $unique_groups.include?(entity)
        # (!) Beware - Due to a SketchUp bug this is sometimes incorrect.
        definition = entity.entities.parent
       else
        definition = entity.definition
       end
       others = find_faces(others, definition.entities,tform * entity.transformation)
      elsif(entity.typename=="Text")
      	# When the user has entered text strings in SketchUp, we export these as well.
        $output_text << entity
      else
         others = others + 1
      end
     end
   end
   others
end

def find_edges(face,tr)
	edges=face.edges
	edges.each{|e|
	  #if e.curve
	  #puts "curve"
	  #else
		if not $unique_edges.include?(e)
			$unique_edges << e
			find_vertices(e,tr)
		end
	  #end
	}
end

def find_vertices(edge,tr)
	verts=edge.vertices
	verts.each{|v|
		if not $unique_points.include?(v)
			$unique_points << v
			$groups_position << tr
		end
	}
	curve = edge.curve
	if (curve)
		if not $circle_center.include?(curve.center)
			$circle_center << curve.center
		end
		 $circle_end << edge.end
		 $circle_begin << edge.start
	end
end

def find_circles

      # This code 'works', (it finds circles, arc's etc, but it doesn't do anything usefull with it.)

      circles = []
      arcs = []

      $unique_edges.each { |ent|
        if ent.curve # is curve?
          if ent.curve.typename != "ArcCurve" # is no arc? -> is polyline or line!
            # polylines << ent.curve if not polylines.index(ent.curve)
          elsif ent.curve.is_polygon? # is polygon?
            # polygons << ent.curve if not polygons.index(ent.curve)
          elsif ent.curve.normal.z != 1 && ent.curve.normal.z != -1 # circle & arc to polyline if not 2d
            # polylines << ent.curve if not polylines.index(ent.curve)
          else
            if ent.curve.end_angle==Math::PI*2
              circles << ent.curve if not circles.index(ent.curve)
              puts "circle found"
            else
              arcs << ent.curve if not arcs.index(ent.curve)
              puts "arc found"
            end
          end
        else
        end
      }

end

def write_header(myFile)
	myFile.puts "# *****************************************************"
	myFile.puts "# *"
	myFile.puts "# *  CalculiX CGX fbd-file exported by SketchUp"
	myFile.puts "# *"
	myFile.puts "# *****************************************************/"
	myFile.puts ""
	myFile.puts "# Parameters :"
	myFile.puts "valu ldv 4"
	myFile.puts ""
end

def	write_points_to_fbd_file(myFile)
	# Write all points to .fbd file
	i=0
	myFile.puts sprintf("# Write %d points\n",$unique_points.length)
	$unique_points.each{|v|
	# Transform local position to a global position
	pts=v.position.transform!($groups_position[i])
	myFile.puts sprintf("pnt P0%d %.2f %.2f %.2f\n",$pointcounter, pts[0].to_mm, pts[1].to_mm, pts[2].to_mm)
	i += 1
	$pointcounter += 1}
	
	myFile.puts "\n# Center of circle(s)"
	$circle_center.each{|c|
	myFile.puts sprintf("pnt C0%d %.2f %.2f %.2f\n",$centercounter, c[0].to_mm, c[1].to_mm, c[2].to_mm)
	$centercounter += 1
	}
	myFile.puts ""
end

def	write_lines_to_fbd_file(myFile)
	# Write all lines to .fbd file
	
 	
 	myFile.puts sprintf("# Write %d lines\n",$unique_edges.length)
	$unique_edges.each{|e|
	# ToDo: Check if edge is a curve
	# curve = e.curve
 	# if (curve)
 	# 	pts = curve.center
 	# 	myFile.puts sprintf("pnt P0%d %.2f %.2f %.2f \n",$counter, pts[0].to_mm, pts[1].to_mm, pts[2].to_mm)
 	# 	$counter += 1
 	# end
	edge1=e.end
	edge2=e.start
	end_index = $unique_points.index(edge1)+1
	start_index = $unique_points.index(edge2)+1
	myFile.puts sprintf("line L0%d P0%d P0%d ldv\n",$linecounter, start_index, end_index)
	$linecounter += 1}

	myFile.puts ""
end

def	write_faces_to_fbd_file(myFile)
	# write all faces as surfaces to .fbd file
	face_index_number = []
	myFile.puts sprintf("# Write %d Surfaces\n",$unique_faces.length)
	$unique_faces.each{|f|
		loop = f.loops
		if loop.length == 1
			# Case: Simple face with no inner faces
			text = sprintf("gsur A0%d + blend ",$facecounter)
			edges=f.edges
			edges.each{|e|
				edge_index = $unique_edges.index(e)+1
				if e.reversed_in? f
					text = text + sprintf("+ L0%d ",edge_index)
				else
					text = text + sprintf("+ L0%d ",edge_index)
				end
				}
			text=text[0..-2]
			text = text + sprintf("\n")
			myFile.puts text
			surfacenumber = $facecounter
			$facecounter += 1
			face_index_number << $facecounter
			myFile.puts sprintf("seta S0%d s A0%d \n",$surfcounter, surfacenumber)
			$surfcounter += 1
		else
			face_index_number << 0 # We need to store a face index for each face
			# Case: Complex face with one or more inner faces
			# Write outerloop first, then the other loops, store outerloop, so we only write it once!
			if not $outer_face.include?(f.outer_loop.face) # Check if we already processed these faces
				$outer_face << f.outer_loop.face
				outer_loop_of_face = f.outer_loop.edges
				text = sprintf("gsur A0%d + blend ",$facecounter)
				outer_loop_of_face.each{|e|
					edge_index = $unique_edges.index(e)+1
					if e.reversed_in? f
						text = text + sprintf("+ L0%d ",edge_index)
					else
						text = text + sprintf("+ L0%d ",edge_index)
					end
					}
				text=text[0..-2]
				text = text + sprintf("\n")
				myFile.puts text
				exterior_loop = $facecounter
				$facecounter += 1

				#Do all other faces
				line_loop_number = []
				loop.each{|b|
					if b.face==f.outer_loop.face
					else
						text = sprintf("gsur A0%d + blend ",$facecounter)
						b.edges.each{|e|
							edge_index = $unique_edges.index(e)+1
							if e.reversed_in? f
								text = text + sprintf("+ L0%d ",edge_index)
							else
								text = text + sprintf("+ L0%d ",edge_index)
							end
							}
						text=text[0..-2]
						text = text + sprintf("\n")
						myFile.puts text
						line_loop_number << $facecounter
						$facecounter += 1
					end
				}
				str = sprintf("seta S0%d s A0%d",$surfcounter,exterior_loop)
				line_loop_number.each{|n|
				str << sprintf(" %d",n)
				}
				str << sprintf("\n")
				myFile.puts str
				$complex_face_index_number << $surfcounter
				$surfcounter += 1
			end
		end
	}
	myFile.puts ""
	return face_index_number
end

def	write_volumes_to_fbd_file(myFile,face_index_number)
	# write all groups as volumes to .fbd file
	face_in_this_group = 0
	$unique_groups.each{|g|
		text = sprintf("seta V0%d s ",$surfcounter)
		g.entities.parent.entities.each{|face|
		next unless face.is_a?(Sketchup::Face)
		# We need to find at least one face in a group
		face_in_this_group = 1
		loop = face.loops
		if loop.length == 1
			face_number = face_index_number[$unique_faces.index(face)]
			text = text + sprintf("S0%d ",face_number-1)
		else
			if not $outer_face2.include?(face.outer_loop.face) # Check if we already processed these faces
				$outer_face2 << face.outer_loop.face
				face_number = $complex_face_index_number[$outer_face.index(face.outer_loop.face)]
				text = text + sprintf("S0%d ",face_number-1)
			end
		end
		}
		if face_in_this_group == 1
		  text=text[0..-2]
		  text = text + sprintf("\n")
		  myFile.puts text
		  volumenumber = $surfcounter
		  $surfcounter += 1
		  myFile.puts sprintf("body B0%d V0%d\n",$surfcounter, volumenumber)
		  $bodycounter += 1
		  face_in_this_group = 0 # Set to 0 again
		end
	}
	myFile.puts ""
end


def	write_text_to_fbd_file(myFile)
	myFile.puts "plot p all"
	myFile.puts "plus l all"
	myFile.puts "plus s all"
	myFile.puts "plus ba all"
	myFile.puts ""
	myFile.puts "#/merg p all"
	myFile.puts "#/merg l all"
	myFile.puts "#/merg s all"
	myFile.puts ""
	myFile.puts "#/div all auto 2. 10. 0.5"
	myFile.puts "#/elty all te10 / he20r / tr6 / qu8r"
	myFile.puts "#/mesh all"
	myFile.puts ""
	myFile.puts "#/send all abq"
	myFile.puts ""
	myFile.puts "prnt se"
	myFile.puts ""
	myFile.puts "#/seta Support A0x"
	myFile.puts "#/comp Support do"
	myFile.puts "#/send Support abq spc 123"
	myFile.puts ""
	myFile.puts "#/seta Load A0x"
	myFile.puts "#/comp Load do"
	myFile.puts "#/comp Load do"
	myFile.puts "#/send Support abq pres 1.0"
end