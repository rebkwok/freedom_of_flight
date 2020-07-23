/**
  The number of milliseconds to ignore clicks on the *same* like
  button, after a button *that was not ignored* was clicked. Used by
  `$(document).ready()`.
  Equal to <code>500</code>.
 */
var MILLS_TO_IGNORE = 500;

/**
   Executes a delete btn click.
 */
const processFailure = function(
   result, status, jqXHR)  {
  //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
  if (result.responseText) {
    vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
  }
   };

const processDeleteCourseType = function()  {

   //In this scope, "this" is the button just clicked on.
   //The "this" in processResult is *not* the button just clicked
   //on.
   const $button_just_clicked_on = $(this);

   //The value of the "data-booking_id" attribute.
   const course_type_id = $button_just_clicked_on.data('course_type_id');

   const processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result.attended + "', status='" + status + "', jqXHR='" + jqXHR + "', booking_id='" + booking_id + "'");

       if(result.deleted === true) {
           $('#row-course-type-' + course_type_id).hide();
       }

       if (result.alert_msg) {
        vNotify.error({text:result.alert_msg, position: 'bottomRight'});
      }

   };

   $.ajax(
       {
          url: '/studioadmin/site-config/course-type/' + course_type_id + '/delete/' ,
          type: "POST",
          dataType: 'json',
          success: processResult,
          error: processFailure
       }
    );
};


$(document).ready(function()  {

  // For the edit tracl/add track button and modal
  $(".edit-course-type").click(function(ev) { // for each add url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#EditCourseTypeModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });
        return false; // prevent the click propagation
    });

   $(".add-course-type").click(function(ev) { // for each add url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#AddCourseTypeModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });
        return false; // prevent the click propagation
    });

    $('.course-type-delete-btn').click(_.debounce(processDeleteCourseType, MILLS_TO_IGNORE, true));

});