/*
  This file must be imported immediately-before the close-</body> tag,
  and after JQuery and Underscore.js are imported.
*/
/**
  The number of milliseconds to ignore clicks on the *same* like
  button, after a button *that was not ignored* was clicked. Used by
  `$(document).ready()`.
  Equal to <code>500</code>.
 */
var MILLS_TO_IGNORE = 500;

/**
   Executes a toggle click. Triggered by clicks on the regular student yes/no links.
 */
const processFailure = function(
   result, status, jqXHR)  {
  //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
  if (result.responseText) {
    vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
  }
   };

const processDeleteSubscription = function()  {

   //In this scope, "this" is the button just clicked on.
   //The "this" in processResult is *not* the button just clicked
   //on.
   const $button_just_clicked_on = $(this);

   //The value of the "data-block_id" attribute.
   const subscription_id = $button_just_clicked_on.data('subscription_id');

   const processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result.attended + "', status='" + status + "', jqXHR='" + jqXHR + "', booking_id='" + booking_id + "'");

       if(result.deleted === true) {
           $('#row-subscription-' + subscription_id).hide();
       }

       if (result.alert_msg) {
        vNotify.error({text:result.alert_msg, position: 'bottomRight'});
      }

   };

   $.ajax(
       {
          url: '/studioadmin/user/subscription/' + subscription_id + '/delete/' ,
          type: "POST",
          dataType: 'json',
          success: processResult,
          error: processFailure
       }
    );
};



/**
   The Ajax "main" function. Attaches the listeners to the elements on
   page load, each of which only take effect every
   <link to MILLS_TO_IGNORE> seconds.

   This protection is only against a single user pressing buttons as fast
   as they can. This is in no way a protection against a real DDOS attack,
   of which almost 100% bypass the client (browser) (they instead
   directly attack the server). Hence client-side protection is pointless.

   - http://stackoverflow.com/questions/28309850/how-much-prevention-of-rapid-fire-form-submissions-should-be-on-the-client-side

   The protection is implemented via Underscore.js' debounce function:
  - http://underscorejs.org/#debounce

   Using this only requires importing underscore-min.js. underscore-min.map
   is not needed.
 */
$(document).ready(function()  {
  /*
    There are many buttons having the class

      td_ajax_book_button

    This attaches a listener to *every one*. Calling this again
    would attach a *second* listener to every button, meaning each
    click would be processed twice.
   */
  $('.subscription-delete-btn').click(_.debounce(processDeleteSubscription, MILLS_TO_IGNORE, true));
  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

    $(".subscriptionedit").click(function(ev) { // for each edit url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#UserSubscriptionModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });

        return false; // prevent the click propagation
    });

    $(".subscriptionadd").click(function(ev) { // for each add url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#UserSubscriptionAddModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });

        return false; // prevent the click propagation
    });

});